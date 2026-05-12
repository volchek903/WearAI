from __future__ import annotations

from aiogram import Dispatcher

from app.handlers.admin_access import router as admin_access_router
from app.handlers.admin_broadcast import router as admin_broadcast_router
from app.handlers.admin_panel import router as admin_panel_router
from app.handlers.animate_photo import router as animate_router
from app.handlers.car_in_hand import router as car_in_hand_router
from app.handlers.cinema_bw import router as cinema_bw_router
from app.handlers.disney_family_heart import router as disney_family_heart_router
from app.handlers.disney_family_wall import router as disney_family_wall_router
from app.handlers.errors import router as errors_router
from app.handlers.extra import router as extra_router
from app.handlers.faq import router as faq_router
from app.handlers.feb23 import router as feb23_router
from app.handlers.feedback import router as feedback_router
from app.handlers.feedback_offer_video import router as feedback_offer_video_router
from app.handlers.glam_collage import router as glam_collage_router
from app.handlers.gpt_image_2 import router as gpt_image_2_router
from app.handlers.gta_style import router as gta_style_router
from app.handlers.lego_style import router as lego_style_router
from app.handlers.love_is import router as love_is_router
from app.handlers.main_defender import router as main_defender_router
from app.handlers.march8 import router as march8_router
from app.handlers.menu import router as menu_router
from app.handlers.motion_control import router as motion_control_router
from app.handlers.music_ace_step import router as music_ace_step_router
from app.handlers.nano_banana import router as nano_banana_router
from app.handlers.radar import router as radar_router
from app.handlers.rear_view_mirror import router as rear_view_mirror_router
from app.handlers.referrals import router as referrals_router
from app.handlers.scenario_model import router as model_router
from app.handlers.scenario_tryon import router as tryon_router
from app.handlers.second_life import router as second_life_router
from app.handlers.seedream_45 import router as seedream_45_router
from app.handlers.seedream_lite import router as seedream_lite_router
from app.handlers.settings import router as settings_router
from app.handlers.sims_style import router as sims_style_router
from app.handlers.start import router as start_router
from app.handlers.video_models import router as video_models_router
from app.handlers.wan_27 import router as wan_27_router
from app.handlers.drift_heart import router as drift_heart_router


def setup_routers(dp: Dispatcher) -> None:
    # Feedback must stay first so its FSM handlers are not shadowed.
    dp.include_router(feedback_router)

    ordered_routers = [
        start_router,
        menu_router,
        video_models_router,
        model_router,
        nano_banana_router,
        gpt_image_2_router,
        seedream_45_router,
        seedream_lite_router,
        wan_27_router,
        drift_heart_router,
        rear_view_mirror_router,
        motion_control_router,
        car_in_hand_router,
        tryon_router,
        love_is_router,
        disney_family_heart_router,
        disney_family_wall_router,
        feb23_router,
        march8_router,
        main_defender_router,
        cinema_bw_router,
        second_life_router,
        radar_router,
        gta_style_router,
        lego_style_router,
        sims_style_router,
        glam_collage_router,
        music_ace_step_router,
        animate_router,
        faq_router,
        feedback_offer_video_router,
        admin_panel_router,
        admin_broadcast_router,
        extra_router,
        admin_access_router,
        referrals_router,
        settings_router,
        errors_router,
    ]
    for router in ordered_routers:
        dp.include_router(router)


__all__ = ["setup_routers"]
