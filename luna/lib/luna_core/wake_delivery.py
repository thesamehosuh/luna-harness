"""Trusted in-process wake receipts. Never serialized into model context."""
def receipt(event):
    if not getattr(event, "internal", False):
        return None
    return (getattr(event, "metadata", None) or {}).get("luna_delivery")


def allowed(event):
    value = receipt(event)
    if not value:
        return True
    try:
        return value["allowed"]() is True
    except Exception:
        return False


def complete(event, status, content="", message_id=""):
    value = receipt(event)
    if value:
        try:
            value["complete"](status, content, message_id)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Wake receipt could not be persisted")
