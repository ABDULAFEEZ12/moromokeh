import datetime
import random
import string


def generate_order_number():
    """Human-friendly order id shown to customers, e.g. MRK-20260918-7F3K.

    This is separate from `payment_reference` (which is what SquadCo and
    the idempotent finalize logic key off of) purely so customers have
    something short and readable to quote over WhatsApp.
    """
    date_part = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"MRK-{date_part}-{suffix}"


def generate_payment_reference():
    date_part = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"mrk_{date_part}_{suffix}"


FULFILLMENT_STATUSES = ["pending", "processing", "shipped", "completed", "cancelled"]
PAYMENT_STATUSES = ["pending", "paid", "failed"]
