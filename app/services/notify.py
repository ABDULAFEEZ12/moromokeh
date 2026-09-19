"""Best-effort order notification email to the store owner.

Never raises - a broken mail server must never fail a checkout that the
customer already paid for. Failures are logged, not surfaced.
"""

import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger("moromokeh")


def send_order_notification(config, order):
    if not (config.get("MAIL_SERVER") and config.get("MAIL_USERNAME") and config.get("MAIL_PASSWORD") and config.get("ORDER_NOTIFY_EMAIL")):
        return
    try:
        items_text = "\n".join(
            f"- {item.get('name')}"
            f"{' (Size ' + item['size'] + ')' if item.get('size') else ''}"
            f" x{item.get('qty', 1)} - NGN {item.get('line_total', 0):,.0f}"
            for item in order.get("items", [])
        ) or "No items listed"
        customer = order.get("customer", {})
        body = (
            f"New paid order: {order.get('order_number')}\n\n"
            f"Customer: {customer.get('name')}\n"
            f"Phone: {customer.get('phone')}\n"
            f"Email: {customer.get('email')}\n"
            f"Total: NGN {order.get('total', 0):,.0f}\n\n"
            f"Items:\n{items_text}\n\n"
            f"Delivery: {customer.get('address')}, {customer.get('city')}, {customer.get('state')}\n"
            f"Note: {customer.get('note') or '-'}"
        )
        msg = MIMEText(body)
        msg["Subject"] = f"New order {order.get('order_number')} - Moromokeh Essential Store"
        msg["From"] = config["MAIL_USERNAME"]
        msg["To"] = config["ORDER_NOTIFY_EMAIL"]
        with smtplib.SMTP(config["MAIL_SERVER"], config["MAIL_PORT"], timeout=10) as server:
            if config["MAIL_USE_TLS"]:
                server.starttls()
            server.login(config["MAIL_USERNAME"], config["MAIL_PASSWORD"])
            server.sendmail(config["MAIL_USERNAME"], [config["ORDER_NOTIFY_EMAIL"]], msg.as_string())
    except Exception as exc:
        logger.warning("Order notification email failed: %s", exc)
