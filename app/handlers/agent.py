from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.agent import AgentCallbacks, agent_panel_kb
from app.keyboards.menu import MenuCallbacks, main_menu_kb
from app.repository.app_settings import (
    AgentPriceBreakdown,
    build_agent_price_breakdown,
    get_agent_daily_free_limit,
    get_agent_request_pricing,
)
from app.repository.agent_documents import (
    add_agent_document,
    count_agent_documents,
    list_agent_documents,
)
from app.repository.agent_memory import add_agent_message, clear_agent_messages, list_recent_agent_messages
from app.repository.agent_settings import (
    ensure_agent_settings,
    rotate_agent_document_session,
    snapshot_agent_settings,
    toggle_agent_setting,
)
from app.repository.generations import (
    CHARGE_SOURCE_DAILY_FREE,
    NoGenerationsLeft,
    PendingGenerationInProgressError,
    charge_agent_request,
    finalize_agent_request,
    refund_agent_request,
)
from app.repository.users import upsert_user
from app.services.wea_agent import (
    UnsupportedDocumentError,
    extract_document_text,
    generate_agent_reply_streaming,
    search_web,
)
from app.states.agent_flow import AgentFlow
from app.utils.tg_markdown import render_markdown_to_html_chunks
from app.utils.support_text import with_support
from app.utils.tg_callback import safe_answer
from app.utils.tg_edit import edit_text_safe
from app.utils.tg_files import tg_file_id_to_bytes
from app.utils.tg_stream import TelegramDraftStreamer

router = Router()
logger = logging.getLogger(__name__)

AGENT_TOGGLE_FIELDS = {
    "web_search_enabled",
    "documents_enabled",
    "memory_enabled",
    "deep_analysis_enabled",
    "quick_mode_enabled",
}


def _mode_label(enabled: bool) -> str:
    return "вкл" if enabled else "выкл"


def _msk_today_key() -> str:
    msk = timezone(timedelta(hours=3))
    return datetime.now(msk).date().isoformat()


def _free_agent_used_today(user) -> int:
    if getattr(user, "free_agent_requests_day", "") != _msk_today_key():
        return 0
    return int(getattr(user, "free_agent_requests_used_today", 0) or 0)


def _total_available_credits(user) -> int:
    return int(getattr(user, "credit_balance", 0) or 0) + int(
        getattr(user, "free_credit_balance", 0) or 0
    )


def _effective_agent_settings(settings, *, is_daily_free: bool):
    if not is_daily_free:
        return settings
    return replace(
        settings,
        web_search_enabled=False,
        documents_enabled=False,
        memory_enabled=False,
        deep_analysis_enabled=False,
        quick_mode_enabled=False,
    )


def _format_agent_breakdown_formula(breakdown: AgentPriceBreakdown) -> str:
    parts = [f"база {int(breakdown.base)}"]
    for label, amount in breakdown.extras:
        parts.append(f"{label} {int(amount)}")
    return " + ".join(parts)


async def _agent_out_of_credits_text(session: AsyncSession, *, settings) -> str:
    pricing = await get_agent_request_pricing(session)
    breakdown = build_agent_price_breakdown(
        pricing,
        memory_enabled=bool(settings.memory_enabled),
        documents_enabled=bool(settings.documents_enabled),
        web_search_enabled=bool(settings.web_search_enabled),
        deep_analysis_enabled=bool(settings.deep_analysis_enabled),
        quick_mode_enabled=bool(settings.quick_mode_enabled),
    )
    return (
        "Не хватает кредитов для следующего запроса.\n\n"
        f"• Базовый запрос: <b>{int(pricing.base)}</b> кредитов.\n"
        f"• Память диалога: <b>+{int(pricing.memory)}</b> кредита.\n"
        f"• Документы: <b>+{int(pricing.documents)}</b> кредита.\n"
        f"• Веб-поиск: <b>+{int(pricing.web_search)}</b> кредит.\n"
        f"• Глубокий анализ: <b>+{int(pricing.deep_analysis)}</b> кредит.\n"
        f"• Быстрый режим: <b>+{int(pricing.quick_mode)}</b> кредит.\n\n"
        f"Для текущего запроса нужно: <b>{int(breakdown.total)}</b> кредитов "
        f"({_format_agent_breakdown_formula(breakdown)}).\n\n"
        "Пополнить баланс можно в разделе «Баланс»."
    )


def _dropped_agent_feature_labels(requested_settings, effective_settings) -> list[str]:
    labels: list[str] = []
    if bool(requested_settings.memory_enabled) and not bool(effective_settings.memory_enabled):
        labels.append("память диалога")
    if bool(requested_settings.documents_enabled) and not bool(effective_settings.documents_enabled):
        labels.append("документы")
    if bool(requested_settings.web_search_enabled) and not bool(effective_settings.web_search_enabled):
        labels.append("веб-поиск")
    if bool(requested_settings.deep_analysis_enabled) and not bool(effective_settings.deep_analysis_enabled):
        labels.append("глубокий анализ")
    if bool(requested_settings.quick_mode_enabled) and not bool(effective_settings.quick_mode_enabled):
        labels.append("быстрый режим")
    return labels


def _format_agent_feature_list(labels: list[str]) -> str:
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} и {labels[1]}"
    return f"{', '.join(labels[:-1])} и {labels[-1]}"


def _describe_next_agent_request(*, settings, pricing, free_limit: int, user) -> str:
    breakdown = build_agent_price_breakdown(
        pricing,
        memory_enabled=bool(settings.memory_enabled),
        documents_enabled=bool(settings.documents_enabled),
        web_search_enabled=bool(settings.web_search_enabled),
        deep_analysis_enabled=bool(settings.deep_analysis_enabled),
        quick_mode_enabled=bool(settings.quick_mode_enabled),
    )
    free_remaining = max(0, int(free_limit) - _free_agent_used_today(user))
    has_free = int(free_limit) > 0 and free_remaining > 0
    has_enough_balance = _total_available_credits(user) >= int(breakdown.total)
    has_addons = bool(breakdown.extras)

    if has_addons and has_enough_balance:
        return (
            f"Следующий запрос будет <b>расширенным платным</b>: спишется "
            f"<b>{int(breakdown.total)}</b> кредитов ({_format_agent_breakdown_formula(breakdown)})."
        )
    if has_addons and has_free:
        return (
            "Следующий запрос будет <b>бесплатным упрощённым</b>: для доп. режимов "
            "не хватает кредитов, поэтому будет использован только базовый режим."
        )
    if has_addons:
        return (
            f"Для следующего запроса нужно минимум <b>{int(breakdown.total)}</b> кредитов "
            f"на балансе ({_format_agent_breakdown_formula(breakdown)})."
        )
    if has_free:
        return "Следующий запрос будет <b>бесплатным базовым</b>."
    if has_enough_balance:
        return (
            f"Следующий запрос будет <b>платным базовым</b>: спишется <b>{int(breakdown.total)}</b> кредитов."
        )
    return (
        f"Бесплатный лимит уже закончился. Для следующего запроса нужно минимум "
        f"<b>{int(breakdown.total)}</b> кредитов на балансе."
    )


def _toggle_mode_message(field_name: str, enabled: bool) -> str:
    if field_name == "documents_enabled":
        return (
            "📄 Работа с документами включена. Агент сможет учитывать текст из документов."
            if enabled
            else "📄 Работа с документами выключена."
        )
    if field_name == "memory_enabled":
        return (
            "🧠 Память диалога включена. Агент сможет учитывать предыдущие сообщения."
            if enabled
            else "🧠 Память диалога выключена."
        )
    if field_name == "web_search_enabled":
        return (
            "🌐 Веб-поиск включён. Агент сможет учитывать найденные материалы из интернета."
            if enabled
            else "🌐 Веб-поиск выключен."
        )
    if field_name == "deep_analysis_enabled":
        return (
            "🔎 Глубокий анализ включён. Ответы станут подробнее, но обычно медленнее."
            if enabled
            else "🔎 Глубокий анализ выключен."
        )
    if field_name == "quick_mode_enabled":
        return (
            "⚡ Быстрый режим включён. Агент будет отвечать короче и быстрее."
            if enabled
            else "⚡ Быстрый режим выключен."
        )
    return "Настройка обновлена."


def _build_agent_pricing_note(*, settings, pricing, free_limit: int, user) -> str:
    breakdown = build_agent_price_breakdown(
        pricing,
        memory_enabled=bool(settings.memory_enabled),
        documents_enabled=bool(settings.documents_enabled),
        web_search_enabled=bool(settings.web_search_enabled),
        deep_analysis_enabled=bool(settings.deep_analysis_enabled),
        quick_mode_enabled=bool(settings.quick_mode_enabled),
    )
    free_remaining = max(0, int(free_limit) - _free_agent_used_today(user))
    balance = _total_available_credits(user)
    free_text = (
        f"• Простых бесплатных запросов осталось сегодня: <b>{free_remaining}</b> из <b>{free_limit}</b>."
        if free_limit > 0
        else "• Простых бесплатных запросов сейчас нет."
    )
    lines = [
        "💳 <b>Как работает оплата</b>",
        f"• Доступно на балансе: <b>{balance}</b> кредитов.",
        free_text,
        f"• Базовый запрос: бесплатно в пределах дневного лимита, затем <b>{int(pricing.base)}</b> кредитов.",
        f"• Память диалога: <b>+{int(pricing.memory)}</b> кредита.",
        f"• Документы: <b>+{int(pricing.documents)}</b> кредита.",
        f"• Веб-поиск: <b>+{int(pricing.web_search)}</b> кредит.",
        f"• Глубокий анализ: <b>+{int(pricing.deep_analysis)}</b> кредит.",
        f"• Быстрый режим: <b>+{int(pricing.quick_mode)}</b> кредит.",
        "• В бесплатном режиме все доп. режимы отключаются, используется только базовый ответ.",
        "",
        f"📌 <b>Текущая стоимость с выбранными режимами</b>: <b>{int(breakdown.total)}</b> кредитов.",
        f"• Формула: <b>{_format_agent_breakdown_formula(breakdown)}</b>",
        "",
        "🎯 <b>Что будет при следующем сообщении</b>",
        f"• {_describe_next_agent_request(settings=settings, pricing=pricing, free_limit=free_limit, user=user)}",
    ]
    return "\n".join(lines)


async def _agent_pricing_note(session: AsyncSession, *, settings, user) -> str:
    pricing = await get_agent_request_pricing(session)
    free_limit = await get_agent_daily_free_limit(session)
    return _build_agent_pricing_note(
        settings=settings,
        pricing=pricing,
        free_limit=free_limit,
        user=user,
    )


def _build_agent_request_badge_text(*, charge, requested_settings, effective_settings, requested_breakdown) -> str:
    if charge.source == CHARGE_SOURCE_DAILY_FREE:
        dropped = _dropped_agent_feature_labels(requested_settings, effective_settings)
        if dropped:
            return (
                "🆓 <b>Бесплатный упрощённый запрос</b>\n"
                f"В этом ответе не будут использоваться: <b>{_format_agent_feature_list(dropped)}</b>."
            )
        return (
            "🆓 <b>Бесплатный базовый запрос</b>\n"
            "Используется ваш дневной бесплатный лимит."
        )

    if requested_breakdown.extras:
        return (
            f"💳 <b>Платный расширенный запрос</b> • <b>{charge.amount}</b> кредитов\n"
            f"Списывается: <b>{_format_agent_breakdown_formula(requested_breakdown)}</b>."
        )
    return f"💳 <b>Платный базовый запрос</b> • <b>{charge.amount}</b> кредитов"


async def _send_agent_request_badge(
    message: Message,
    *,
    charge,
    requested_settings,
    effective_settings,
    requested_breakdown,
) -> None:
    await message.answer(
        _build_agent_request_badge_text(
            charge=charge,
            requested_settings=requested_settings,
            effective_settings=effective_settings,
            requested_breakdown=requested_breakdown,
        ),
        parse_mode="HTML",
    )


def _agent_panel_text(
    *,
    settings,
    document_count: int,
    pricing_note: str | None = None,
    note: str | None = None,
) -> str:
    lines = [
        "🤖 <b>Агент WeaRai</b>",
        "",
        "Напишите сообщение или отправьте документ. Агент ответит в этом разделе.",
        "",
        "Текущие режимы:",
        f"• Веб-поиск: {_mode_label(settings.web_search_enabled)}",
        f"• Работа с документами: {_mode_label(settings.documents_enabled)}",
        f"• Память диалога: {_mode_label(settings.memory_enabled)}",
        f"• Глубокий анализ: {_mode_label(settings.deep_analysis_enabled)}",
        f"• Быстрый режим: {_mode_label(settings.quick_mode_enabled)}",
        "",
        f"Документов в текущей сессии: <b>{max(0, int(document_count))}</b>",
    ]
    if pricing_note:
        lines.extend(["", pricing_note.strip()])
    if settings.quick_mode_enabled and settings.deep_analysis_enabled:
        lines.extend(
            [
                "",
                "⚡ Быстрый режим сейчас имеет приоритет и сокращает глубину анализа.",
            ]
        )
    if note:
        lines.extend(["", note.strip()])
    return "\n".join(lines)


async def _render_agent_panel(
    target: CallbackQuery | Message,
    *,
    session: AsyncSession,
    user,
    settings,
    document_count: int,
    note: str | None = None,
) -> None:
    pricing_note = await _agent_pricing_note(session, settings=settings, user=user)
    text = _agent_panel_text(
        settings=settings,
        document_count=document_count,
        pricing_note=pricing_note,
        note=note,
    )
    markup = agent_panel_kb(settings, document_count=document_count)
    if isinstance(target, CallbackQuery):
        await edit_text_safe(target, text, reply_markup=markup, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")


async def _load_agent_view(session: AsyncSession, *, tg_id: int, username: str | None):
    user = await upsert_user(session, tg_id, username)
    settings = await ensure_agent_settings(session, user.id)
    document_count = await count_agent_documents(
        session,
        user_id=user.id,
        session_key=settings.document_session_key,
    )
    return user, settings, document_count


async def _send_agent_reply(
    message: Message,
    *,
    text: str,
    settings,
    document_count: int,
) -> None:
    chunks = render_markdown_to_html_chunks(text)
    markup = agent_panel_kb(settings, document_count=document_count)
    for idx, part in enumerate(chunks):
        is_last = idx == len(chunks) - 1
        await message.answer(
            part or " ",
            parse_mode="HTML",
            reply_markup=markup if is_last else None,
        )


async def _answer_query_with_agent(
    message: Message,
    *,
    session: AsyncSession,
    tg_id: int,
    user_id: int,
    settings,
    user_text: str,
) -> None:
    requested_settings = snapshot_agent_settings(settings)
    pricing = await get_agent_request_pricing(session)
    requested_breakdown = build_agent_price_breakdown(
        pricing,
        memory_enabled=bool(requested_settings.memory_enabled),
        documents_enabled=bool(requested_settings.documents_enabled),
        web_search_enabled=bool(requested_settings.web_search_enabled),
        deep_analysis_enabled=bool(requested_settings.deep_analysis_enabled),
        quick_mode_enabled=bool(requested_settings.quick_mode_enabled),
    )
    charge = await charge_agent_request(
        session,
        tg_id,
        credits_override=int(requested_breakdown.total),
        prefer_paid=int(requested_breakdown.total) > int(requested_breakdown.base),
    )
    effective_settings = _effective_agent_settings(
        requested_settings,
        is_daily_free=charge.source == CHARGE_SOURCE_DAILY_FREE,
    )
    draft_streamer = TelegramDraftStreamer(message)
    try:
        await _send_agent_request_badge(
            message,
            charge=charge,
            requested_settings=requested_settings,
            effective_settings=effective_settings,
            requested_breakdown=requested_breakdown,
        )
        if draft_streamer.enabled:
            await draft_streamer.start()
        if not draft_streamer.enabled:
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

        history = []
        if effective_settings.memory_enabled:
            history = await list_recent_agent_messages(
                session,
                user_id=user_id,
                limit=16,
            )

        documents = []
        if effective_settings.documents_enabled:
            documents = await list_agent_documents(
                session,
                user_id=user_id,
                session_key=settings.document_session_key,
                limit=20,
            )

        search_results = []
        if effective_settings.web_search_enabled:
            search_results = await search_web(
                user_text,
                quick_mode=effective_settings.quick_mode_enabled,
            )

        reply = await generate_agent_reply_streaming(
            user_text,
            settings=effective_settings,
            history=history,
            documents=documents,
            search_results=search_results,
            on_delta=draft_streamer.push,
        )
        if not reply:
            raise RuntimeError("Agent stream returned empty reply")

        await draft_streamer.flush(force=True)

        document_count = await count_agent_documents(
            session,
            user_id=user_id,
            session_key=settings.document_session_key,
        )
        await _send_agent_reply(
            message,
            text=reply,
            settings=snapshot_agent_settings(settings),
            document_count=document_count,
        )
        await finalize_agent_request(session, tg_id)
        try:
            await add_agent_message(session, user_id=user_id, role="user", content=user_text)
            await add_agent_message(session, user_id=user_id, role="assistant", content=reply)
        except Exception:
            logger.exception("agent memory append failed: user_id=%s", user_id)
    except Exception:
        logger.exception(
            "agent request failed after charge: tg_id=%s source=%s amount=%s",
            tg_id,
            charge.source,
            charge.amount,
        )
        try:
            await refund_agent_request(session, tg_id)
        except Exception:
            logger.exception("agent request refund failed: tg_id=%s", tg_id)
        raise


@router.callback_query(F.data == MenuCallbacks.TEXT)
async def open_agent_section(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    user, settings, document_count = await _load_agent_view(
        session,
        tg_id=call.from_user.id,
        username=call.from_user.username,
    )
    await state.clear()
    await state.set_state(AgentFlow.chat)
    await _render_agent_panel(
        call,
        session=session,
        user=user,
        settings=snapshot_agent_settings(settings),
        document_count=document_count,
    )
    await safe_answer(call)


@router.callback_query(F.data.startswith(AgentCallbacks.TOGGLE_PREFIX))
async def toggle_agent_mode(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    field_name = str(call.data or "").removeprefix(AgentCallbacks.TOGGLE_PREFIX)
    if field_name not in AGENT_TOGGLE_FIELDS:
        await safe_answer(call, "Неизвестный режим 😕", show_alert=True)
        return

    user, _, _ = await _load_agent_view(
        session,
        tg_id=call.from_user.id,
        username=call.from_user.username,
    )
    settings = await toggle_agent_setting(session, user.id, field_name)
    document_count = await count_agent_documents(
        session,
        user_id=user.id,
        session_key=settings.document_session_key,
    )
    pricing = await get_agent_request_pricing(session)
    free_limit = await get_agent_daily_free_limit(session)
    toggle_note = _toggle_mode_message(field_name, bool(getattr(settings, field_name)))
    next_request_note = _describe_next_agent_request(
        settings=snapshot_agent_settings(settings),
        pricing=pricing,
        free_limit=free_limit,
        user=user,
    )
    await state.set_state(AgentFlow.chat)
    await _render_agent_panel(
        call,
        session=session,
        user=user,
        settings=snapshot_agent_settings(settings),
        document_count=document_count,
        note=f"{toggle_note}\n{next_request_note}",
    )
    await safe_answer(call)


@router.callback_query(F.data == AgentCallbacks.CLEAR_MEMORY)
async def clear_agent_memory_handler(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    user, settings, document_count = await _load_agent_view(
        session,
        tg_id=call.from_user.id,
        username=call.from_user.username,
    )
    await clear_agent_messages(session, user_id=user.id)
    await state.set_state(AgentFlow.chat)
    await _render_agent_panel(
        call,
        session=session,
        user=user,
        settings=snapshot_agent_settings(settings),
        document_count=document_count,
        note="Память диалога очищена.",
    )
    await safe_answer(call)


@router.callback_query(F.data == AgentCallbacks.CLEAR_DOCUMENTS)
async def clear_agent_documents_handler(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    user, _, _ = await _load_agent_view(
        session,
        tg_id=call.from_user.id,
        username=call.from_user.username,
    )
    settings = await rotate_agent_document_session(session, user.id)
    await state.set_state(AgentFlow.chat)
    await _render_agent_panel(
        call,
        session=session,
        user=user,
        settings=snapshot_agent_settings(settings),
        document_count=0,
        note="Документы текущей сессии очищены.",
    )
    await safe_answer(call)


@router.callback_query(F.data == AgentCallbacks.BACK_TO_MENU)
async def back_to_main_menu_from_agent(
    call: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.clear()
    await edit_text_safe(call, "Главное меню 👇", reply_markup=main_menu_kb())
    await safe_answer(call)


@router.message(AgentFlow.chat, F.document)
async def agent_document_message(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if message.document is None or message.from_user is None:
        return

    user, settings, document_count = await _load_agent_view(
        session,
        tg_id=message.from_user.id,
        username=message.from_user.username,
    )
    await state.set_state(AgentFlow.chat)

    try:
        file_bytes = await tg_file_id_to_bytes(
            message.bot,
            message.document.file_id,
            tg_id=message.from_user.id,
        )
        extracted_text = extract_document_text(
            file_bytes,
            file_name=message.document.file_name,
            mime_type=message.document.mime_type,
        )
    except UnsupportedDocumentError:
        await message.answer(
            "Не удалось извлечь текст из этого документа. Сейчас лучше всего работают TXT, MD, CSV, JSON, HTML, XML, DOCX и часть PDF.",
            reply_markup=agent_panel_kb(
                snapshot_agent_settings(settings),
                document_count=document_count,
            ),
        )
        return
    except Exception:
        logger.exception("agent_document_message failed")
        await message.answer(
            with_support("Не удалось обработать документ 😕"),
            reply_markup=agent_panel_kb(
                snapshot_agent_settings(settings),
                document_count=document_count,
            ),
        )
        return

    await add_agent_document(
        session,
        user_id=user.id,
        session_key=settings.document_session_key,
        telegram_file_id=message.document.file_id,
        file_name=message.document.file_name,
        mime_type=message.document.mime_type,
        extracted_text=extracted_text,
    )

    document_count = await count_agent_documents(
        session,
        user_id=user.id,
        session_key=settings.document_session_key,
    )
    caption_text = (message.caption or "").strip()
    if not caption_text:
        note = "Документ добавлен в текущую сессию."
        if not settings.documents_enabled:
            note += " Сейчас режим работы с документами выключен, поэтому документ пока не будет использоваться в ответах."
        await _render_agent_panel(
            message,
            session=session,
            user=user,
            settings=snapshot_agent_settings(settings),
            document_count=document_count,
            note=note,
        )
        return

    try:
        await _answer_query_with_agent(
            message,
            session=session,
            tg_id=message.from_user.id,
            user_id=user.id,
            settings=settings,
            user_text=caption_text,
        )
    except PendingGenerationInProgressError:
        await message.answer(
            "У вас уже обрабатывается другой запрос. Дождитесь завершения текущей операции.",
        )
    except NoGenerationsLeft:
        await message.answer(
            await _agent_out_of_credits_text(session, settings=settings),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("agent_document_message query failed")
        await message.answer(with_support("Не удалось получить ответ агента 😕"))


@router.message(AgentFlow.chat, F.text)
async def agent_text_message(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if message.from_user is None:
        return

    user_text = (message.text or "").strip()
    if not user_text:
        await message.answer("Нужен текстовый запрос ✍️")
        return

    user, settings, _ = await _load_agent_view(
        session,
        tg_id=message.from_user.id,
        username=message.from_user.username,
    )
    await state.set_state(AgentFlow.chat)

    try:
        await _answer_query_with_agent(
            message,
            session=session,
            tg_id=message.from_user.id,
            user_id=user.id,
            settings=settings,
            user_text=user_text,
        )
    except PendingGenerationInProgressError:
        await message.answer(
            "У вас уже обрабатывается другой запрос. Дождитесь завершения текущей операции.",
        )
    except NoGenerationsLeft:
        await message.answer(
            await _agent_out_of_credits_text(session, settings=settings),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("agent_text_message failed")
        await message.answer(with_support("Не удалось получить ответ агента 😕"))


@router.message(AgentFlow.chat)
async def agent_unsupported_message(
    message: Message,
    session: AsyncSession,
) -> None:
    if message.from_user is None:
        return

    _, settings, document_count = await _load_agent_view(
        session,
        tg_id=message.from_user.id,
        username=message.from_user.username,
    )
    await message.answer(
        "В этом разделе отправьте текстовое сообщение или документ.",
        reply_markup=agent_panel_kb(
            snapshot_agent_settings(settings),
            document_count=document_count,
        ),
    )
