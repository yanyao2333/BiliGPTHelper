import loguru

LOGGER = loguru.logger


def custom_format(record):
    name = f"「{record['extra']['name']}」"
    record["extra"]["name"] = name
    format_string = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {extra[name]} {message}"
    log_message = format_string.format(**record)
    return log_message
