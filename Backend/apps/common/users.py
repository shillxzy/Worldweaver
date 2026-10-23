"""How other people are shown to each other in shared projects."""


def display_name(user):
    """The profile name, or the part of the email before "@" (full addresses are not shown to everyone)."""
    if user is None:
        return ""
    profile = getattr(user, "profile", None)
    name = getattr(profile, "display_name", "") if profile is not None else ""
    return name or (user.email or user.get_username()).split("@")[0]
