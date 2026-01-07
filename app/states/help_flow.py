from aiogram.fsm.state import State, StatesGroup


class HelpFlow(StatesGroup):
    input = State()  # пользователь вводит детали для генерации
    ready = State()  # показываем сгенерированный текст и даём "использовать/назад"
