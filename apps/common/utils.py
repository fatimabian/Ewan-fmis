def initials(value):
    return "".join(part[0].upper() for part in value.split()[:2])
