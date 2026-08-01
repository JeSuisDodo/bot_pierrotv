def format(number: int) -> str:
    """Retourne le nombre avec une virgule tous les 3 chiffres"""
    return "{0:,}".format(number)


def format_seconds(seconds: int) -> str:
    """Convertit des secondes en jours/heures/minutes/secondes"""
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{days}j {hours}h {minutes}m {seconds}s"
