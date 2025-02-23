import logging
import random
import datetime
import asyncio
from io import BytesIO

import stripe
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)

# ------------------------
# Logging Setup
# ------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------------
# Stripe Setup
# ------------------------
stripe.api_key = "sk_test_51QvXFNFjtYUjYZLS74K1uN7Wd1TGXXFrlCp6XzEI8vBLvfVqrFQHha0vU0lGZAVoWye2Bh8hXm1US1dso7NGWkHx00ajYl90sn"

# ------------------------
# In-Memory Data Structures
# ------------------------
premium_users = {}  # { "user_id": {"expiry": datetime_object} }
# Cards are stored per-user in context.user_data['cards']

# Designated owner username (without @)
OWNER_USERNAME = "offx_sahil"

# ------------------------
# Utility Functions
# ------------------------

def luhn_checksum(card_number: str) -> int:
    """Calculate Luhn checksum for generating valid card numbers."""
    def digits_of(n):
        return [int(d) for d in str(n)]
    digits = digits_of(card_number)
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    checksum = sum(odd_digits)
    for d in even_digits:
        checksum += sum(digits_of(d * 2))
    return checksum % 10

def generate_card(bin_number: str) -> str:
    """
    Generate a single card using a 6-digit BIN and a Luhn check digit.
    Format: 6-digit BIN + random digits until length 15, then 1 check digit.
    """
    card_number = bin_number
    while len(card_number) < 15:
        card_number += str(random.randint(0, 9))
    check_digit = (10 - luhn_checksum(int(card_number) * 10)) % 10
    return card_number + str(check_digit)

async def check_card_async(card: str) -> str:
    """
    Asynchronously check a card's validity using Stripe.
    Returns a string in the format "card|STATUS" where STATUS is APPROVED, DECLINED, or RISK.
    """
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: stripe.PaymentMethod.create(
                type="card",
                card={
                    "number": card,
                    "exp_month": 12,
                    "exp_year": 2025,
                    "cvc": "123",
                },
            )
        )
        return f"{card}|APPROVED"
    except stripe.error.CardError:
        return f"{card}|DECLINED"
    except Exception:
        return f"{card}|RISK"

def classify_result(result_line: str) -> str:
    """Extracts the status from a result line in the format 'card|STATUS'."""
    parts = result_line.split('|')
    if len(parts) >= 2:
        return parts[-1]
    return "UNKNOWN"

# ------------------------
# Bot Command Handlers
# ------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start command: sends welcome message with inline keyboard."""
    welcome_text = (
        "🤖 **Bot Status:** working ✅\n\n"
        "This bot is designed to include all the tools you need for carding.\n"
        "📂 Upload a file containing only the cards and I'll check them.\n\n"
        "❗ **Important:** Correct card format is: `CC|MM|YYYY|CVV`\n\n"
        "⏳ You can use the bot for half an hour a day for free via the gift button below.\n"
    )
    keyboard = [
        [
            InlineKeyboardButton("🎁 Daily Gift", callback_data="daily_gift"),
            InlineKeyboardButton("💳 Buy Subscription", callback_data="buy_sub"),
        ],
        [
            InlineKeyboardButton("🛒 Accounts Store", callback_data="accounts_store"),
            InlineKeyboardButton("💸 Free Credits", callback_data="free_credits"),
        ],
        [
            InlineKeyboardButton("👨‍💻 Developer/Owner", callback_data="dev_info"),
            InlineKeyboardButton("🔓 Owner Mode", callback_data="owner_mode"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline keyboard button presses."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "daily_gift":
        await query.edit_message_text("🎁 Here is your Daily Gift! Enjoy 🎉")
    elif data == "buy_sub":
        await query.edit_message_text("💳 To buy a subscription, use `/plan <user_id> <days>` or contact admin.", parse_mode="Markdown")
    elif data == "accounts_store":
        await query.edit_message_text("🛒 Welcome to the Accounts Store. We have many accounts for sale.")
    elif data == "free_credits":
        await query.edit_message_text("💸 Earn free credits by inviting friends or completing tasks!")
    elif data == "dev_info":
        await query.edit_message_text("👨‍💻 Developer/Owner: @offx_sahil")
    elif data == "owner_mode":
        user = query.from_user
        if user.username and user.username.lower() == OWNER_USERNAME.lower():
            expiry = datetime.datetime.now() + datetime.timedelta(days=365 * 100)  # 100 years premium
            premium_users[str(user.id)] = {"expiry": expiry}
            await query.edit_message_text("🔓 Owner Mode Activated: You are premium for 100 years!")
        else:
            await query.edit_message_text("❌ Owner Mode is only available for the designated owner.")
    else:
        await query.edit_message_text("❓ Unknown action.")

async def gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /gen command: generates card numbers from a provided 6-digit BIN."""
    if not context.args:
        await update.message.reply_text("Usage: `/gen <6-digit BIN> <count (optional)>`\nExample: `/gen 123456 50`", parse_mode="Markdown")
        return
    bin_number = context.args[0]
    if len(bin_number) != 6 or not bin_number.isdigit():
        await update.message.reply_text("❌ Invalid BIN. Please enter exactly 6 digits.")
        return
    count = 20
    if len(context.args) > 1:
        try:
            count = int(context.args[1])
        except ValueError:
            await update.message.reply_text("ℹ️ Invalid count provided. Using default count of 20.")
    cards = [generate_card(bin_number) for _ in range(count)]
    context.user_data['cards'] = cards
    await update.message.reply_text(f"✅ Generated {len(cards)} cards:\n" + "\n".join(cards))

async def upload_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles TXT file uploads containing card numbers."""
    document = update.message.document
    if not document:
        await update.message.reply_text("❌ Please upload a valid TXT file.")
        return
    if document.file_name.lower().endswith(".txt"):
        file_obj = await document.get_file()
        file_bytes = await file_obj.download_as_bytearray()
        text = file_bytes.decode("utf-8", errors="ignore")
        cards = [line.strip() for line in text.replace(",", "\n").split("\n") if line.strip()]
        if not cards:
            await update.message.reply_text("❌ No valid card numbers found in the file.")
            return
        context.user_data['cards'] = cards
        await update.message.reply_text(f"✅ File processed. Stored {len(cards)} cards. Now use `/chk` to check them.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Please upload a TXT file only.")

async def chk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /chk command: checks all stored cards and returns a summary."""
    if 'cards' not in context.user_data or not context.user_data['cards']:
        await update.message.reply_text("❌ No cards available. Please generate using `/gen` or upload a TXT file.")
        return
    cards = context.user_data['cards']
    await update.message.reply_text(f"⏳ Checking {len(cards)} cards, please wait...")
    tasks = [check_card_async(card) for card in cards]
    results = await asyncio.gather(*tasks)
    approved_count = sum(1 for r in results if classify_result(r) == "APPROVED")
    declined_count = sum(1 for r in results if classify_result(r) == "DECLINED")
    risk_count = sum(1 for r in results if classify_result(r) == "RISK")
    total = len(results)
    summary_msg = (
        f"📊 **Check Summary**\n\n"
        f"✅ APPROVED: [{approved_count}]\n"
        f"❌ DECLINED: [{declined_count}]\n"
        f"⚠️ RISK: [{risk_count}]\n"
        f"💀 TOTAL: [{total}]\n\n"
        "Detailed Results:\n" + "\n".join(results)
    )
    for chunk in [summary_msg[i:i+4000] for i in range(0, len(summary_msg), 4000)]:
        await update.message.reply_text(chunk, parse_mode="Markdown")

async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /plan command: activates a premium plan for a specified user."""
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Usage: `/plan <user_id> <days>`", parse_mode="Markdown")
        return
    try:
        target_user_id = str(args[0])
        duration_days = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid arguments. Ensure days is an integer.")
        return
    now = datetime.datetime.now()
    expiry = now + datetime.timedelta(days=duration_days)
    premium_users[target_user_id] = {"expiry": expiry}
    reply_text = (
        "💎 **Premium Plan Activated** ✅\n\n"
        f"• User: `{target_user_id}`\n"
        f"• Duration: `{duration_days}` day(s)\n"
        f"• Expires: `{expiry.strftime('%Y-%m-%d %H:%M:%S')}`"
    )
    await update.message.reply_text(reply_text, parse_mode="Markdown")

async def check_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /check_premium command: checks the premium status of a user."""
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: `/check_premium <user_id>`", parse_mode="Markdown")
        return
    user_id = args[0]
    if user_id not in premium_users:
        await update.message.reply_text("❌ User not premium.")
        return
    data = premium_users[user_id]
    expiry = data["expiry"]
    now = datetime.datetime.now()
    if now > expiry:
        await update.message.reply_text("⏰ Premium expired.")
        del premium_users[user_id]
    else:
        remain = expiry - now
        hours_left = int(remain.total_seconds() // 3600)
        await update.message.reply_text(f"✅ User `{user_id}` is premium. Expires in about **{hours_left}** hours.", parse_mode="Markdown")

# ------------------------
# Main Bot Runner
# ------------------------
async def main():
    bot_token = "7111858885:AAHGw0SrP5aJsKBGrjylBZDz7aPbE2CbAiA"  # Replace with your actual Telegram bot token
    # Build the application without specifying timezone
    application = ApplicationBuilder().token(bot_token).build()
    # Disable job queue to remove any timezone-related errors
    application.job_queue.stop()
    application.job_queue = None

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("gen", gen))
    application.add_handler(CommandHandler("chk", chk))
    application.add_handler(CommandHandler("plan", plan))
    application.add_handler(CommandHandler("check_premium", check_premium))
    application.add_handler(CallbackQueryHandler(inline_callback))
    application.add_handler(MessageHandler(filters.Document.FileExtension("txt"), upload_file))

    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
