import asyncio
from pathlib import Path
from .logger import logger

# Для Telegram уведомлений
try:
    from telegram import Bot
    from telegram.error import TelegramError
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    

class TelegramNotifier:
    """Класс для отправки уведомлений в Telegram"""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot = None

        if TELEGRAM_AVAILABLE:
            try:
                self.bot = Bot(token=bot_token)
                logger.info("Telegram бот инициализирован")
            except Exception as e:
                logger.error(f"Ошибка инициализации Telegram бота: {e}")

    async def send_message(self, text: str, parse_mode: str = 'HTML'):
        """Отправка сообщения"""
        if not self.bot:
            return False

        try:
            # Разбиваем длинные сообщения
            max_length = 4096
            if len(text) <= max_length:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode=parse_mode
                )
            else:
                # Разбиваем на части
                parts = [text[i:i + max_length] for i in range(0, len(text), max_length)]
                for part in parts:
                    await self.bot.send_message(
                        chat_id=self.chat_id,
                        text=part,
                        parse_mode=parse_mode
                    )
                    await asyncio.sleep(0.5)  # Небольшая задержка между сообщениями

            return True
        except Exception as e:
            logger.error(f"Ошибка отправки Telegram сообщения: {e}")
            return False

    async def send_file(self, file_path: Path, caption: str = None):
        """Отправка файла"""
        if not self.bot or not file_path.exists():
            return False

        try:
            with open(file_path, 'rb') as f:
                await self.bot.send_document(
                    chat_id=self.chat_id,
                    document=f,
                    caption=caption
                )
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки файла в Telegram: {e}")
            return False