"""
Email Service — uses Gmail SMTP (free)
Sends real purchase order emails when manager approves an action.
"""
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime


GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")  # Gmail App Password (not your real password)
MANAGER_EMAIL = os.getenv("MANAGER_EMAIL", "anandshaishav@gmail.com")


def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an email via Gmail SMTP. Returns True if sent successfully."""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print(f"[Email] Skipping — GMAIL_USER or GMAIL_APP_PASSWORD not set")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"STOK Inventory <{GMAIL_USER}>"
        msg["To"] = to
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, to, msg.as_string())

        print(f"[Email] Sent '{subject}' to {to}")
        return True
    except Exception as e:
        print(f"[Email] Failed to send to {to}: {e}")
        return False


def send_purchase_order_email(action, sku, supplier=None) -> bool:
    """Send PO email to manager when an order action is approved."""
    supplier_name = supplier.name if supplier else "Unknown Supplier"
    supplier_email = supplier.contact_email if supplier and supplier.contact_email else "N/A"
    qty = action.recommended_qty or 0
    value = action.recommended_value or 0
    unit_cost = round(value / qty, 2) if qty > 0 else 0

    subject = f"[STOK] PO Approved — {sku.name} ({qty} units)"

    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px;">
    <div style="max-width:600px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
      <div style="background:#0a0a0f;padding:24px;text-align:center">
        <h1 style="color:#00ff88;margin:0;font-size:24px;letter-spacing:2px">STOK</h1>
        <p style="color:#6b6b88;margin:6px 0 0;font-size:12px">Purchase Order Approved</p>
      </div>
      <div style="padding:28px">
        <div style="background:#f0fff8;border:1px solid #00cc66;border-radius:6px;padding:16px;margin-bottom:20px">
          <p style="margin:0;color:#006633;font-weight:bold;font-size:14px">✓ Order Approved & Executed</p>
          <p style="margin:4px 0 0;color:#009944;font-size:12px">{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
        </div>

        <h2 style="font-size:18px;margin:0 0 16px;color:#1a1a2e">{sku.name}</h2>

        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <tr style="background:#f8f8f8">
            <td style="padding:10px 12px;color:#666;border-bottom:1px solid #eee">SKU Code</td>
            <td style="padding:10px 12px;font-weight:600;border-bottom:1px solid #eee">{sku.sku_code}</td>
          </tr>
          <tr>
            <td style="padding:10px 12px;color:#666;border-bottom:1px solid #eee">Quantity Ordered</td>
            <td style="padding:10px 12px;font-weight:600;border-bottom:1px solid #eee">{qty} units</td>
          </tr>
          <tr style="background:#f8f8f8">
            <td style="padding:10px 12px;color:#666;border-bottom:1px solid #eee">Unit Cost</td>
            <td style="padding:10px 12px;font-weight:600;border-bottom:1px solid #eee">${unit_cost}</td>
          </tr>
          <tr>
            <td style="padding:10px 12px;color:#666;border-bottom:1px solid #eee">Total Value</td>
            <td style="padding:10px 12px;font-weight:700;color:#0a7a3c;border-bottom:1px solid #eee">${value:,.2f}</td>
          </tr>
          <tr style="background:#f8f8f8">
            <td style="padding:10px 12px;color:#666;border-bottom:1px solid #eee">Supplier</td>
            <td style="padding:10px 12px;font-weight:600;border-bottom:1px solid #eee">{supplier_name}</td>
          </tr>
          <tr>
            <td style="padding:10px 12px;color:#666">Supplier Email</td>
            <td style="padding:10px 12px;font-weight:600">{supplier_email}</td>
          </tr>
        </table>

        <div style="background:#fffbf0;border:1px solid #ffd166;border-radius:6px;padding:14px;margin-top:20px">
          <p style="margin:0;font-size:12px;color:#664d00"><strong>AI Justification:</strong><br>{action.justification}</p>
        </div>

        <div style="margin-top:20px;padding-top:16px;border-top:1px solid #eee;font-size:11px;color:#999;text-align:center">
          This action was approved via STOK Agentic Inventory Manager.<br>
          Please contact your supplier to confirm the order.
        </div>
      </div>
    </div>
    </body></html>
    """
    return send_email(MANAGER_EMAIL, subject, html)


def send_markdown_email(action, sku) -> bool:
    """Send email when a price markdown is approved."""
    change_pct = abs(action.recommended_value or 15)
    subject = f"[STOK] Price Markdown Approved — {sku.name} (-{change_pct}%)"

    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px;">
    <div style="max-width:600px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
      <div style="background:#0a0a0f;padding:24px;text-align:center">
        <h1 style="color:#00ff88;margin:0;font-size:24px;letter-spacing:2px">STOK</h1>
        <p style="color:#6b6b88;margin:6px 0 0;font-size:12px">Price Change Approved</p>
      </div>
      <div style="padding:28px">
        <h2 style="font-size:18px;margin:0 0 16px">{sku.name} — {sku.sku_code}</h2>
        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <tr style="background:#f8f8f8">
            <td style="padding:10px 12px;color:#666;border-bottom:1px solid #eee">Action</td>
            <td style="padding:10px 12px;font-weight:600;color:#cc4400;border-bottom:1px solid #eee">Markdown -{change_pct}%</td>
          </tr>
          <tr>
            <td style="padding:10px 12px;color:#666;border-bottom:1px solid #eee">Current Price</td>
            <td style="padding:10px 12px;font-weight:600;border-bottom:1px solid #eee">${sku.unit_price or 'N/A'}</td>
          </tr>
          <tr style="background:#f8f8f8">
            <td style="padding:10px 12px;color:#666">New Price</td>
            <td style="padding:10px 12px;font-weight:700;color:#0a7a3c">${round((sku.unit_price or 0) * (1 - change_pct/100), 2)}</td>
          </tr>
        </table>
        <div style="background:#fffbf0;border:1px solid #ffd166;border-radius:6px;padding:14px;margin-top:20px">
          <p style="margin:0;font-size:12px;color:#664d00"><strong>Reason:</strong><br>{action.justification}</p>
        </div>
      </div>
    </div>
    </body></html>
    """
    return send_email(MANAGER_EMAIL, subject, html)


def send_agent_summary_email(actions_created: int, skus_scanned: int, urgent_count: int) -> bool:
    """Send hourly agent summary email if there are urgent actions."""
    if urgent_count == 0:
        return False  # Don't spam — only email when urgent actions exist

    subject = f"[STOK] ⚠️ {urgent_count} Urgent Action{'s' if urgent_count > 1 else ''} Need Your Review"

    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px;">
    <div style="max-width:600px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
      <div style="background:#0a0a0f;padding:24px;text-align:center">
        <h1 style="color:#00ff88;margin:0;font-size:24px;letter-spacing:2px">STOK</h1>
        <p style="color:#6b6b88;margin:6px 0 0;font-size:12px">Hourly Agent Report</p>
      </div>
      <div style="padding:28px">
        <div style="background:#fff0f0;border:1px solid #ff4757;border-radius:6px;padding:16px;margin-bottom:20px;text-align:center">
          <p style="margin:0;font-size:28px;font-weight:bold;color:#cc0000">{urgent_count}</p>
          <p style="margin:4px 0 0;color:#cc0000;font-size:14px">Urgent action{'s' if urgent_count > 1 else ''} require your immediate review</p>
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:20px">
          <tr style="background:#f8f8f8">
            <td style="padding:10px 12px;color:#666;border-bottom:1px solid #eee">SKUs Scanned</td>
            <td style="padding:10px 12px;font-weight:600;border-bottom:1px solid #eee">{skus_scanned}</td>
          </tr>
          <tr>
            <td style="padding:10px 12px;color:#666">New Actions Created</td>
            <td style="padding:10px 12px;font-weight:600">{actions_created}</td>
          </tr>
        </table>
        <div style="text-align:center">
          <a href="{os.getenv('RENDER_EXTERNAL_URL', 'https://stok-inventory.onrender.com')}"
             style="background:#00ff88;color:#0a0a0f;padding:12px 28px;border-radius:6px;text-decoration:none;font-weight:bold;font-size:14px">
            Review Actions Now →
          </a>
        </div>
      </div>
    </div>
    </body></html>
    """
    return send_email(MANAGER_EMAIL, subject, html)
