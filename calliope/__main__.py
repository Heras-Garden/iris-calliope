import logging

from .bot import Calliope
from .config import Settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    bot = Calliope(settings)
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
