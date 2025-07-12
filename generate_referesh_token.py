import logging
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
)
import sys
from fyers_apiv3 import fyersModel
from credentials.credentials import appId, app_secret, redirect_url, TARGET_USER_ID, BOT_TOKEN
from config import GCS_BUCKET_NAME, REFRESH_TOKEN_FILE_PATH

import os
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "credentials/smr-v3-creds.json"

# Add GCS imports
from google.cloud import storage
import os


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_auth_token() -> str:
    """
    Generates the authorization URL for the user to log in and get the auth code.
    """
    response_type = "code"
    grant_type = "authorization_code"
    
    appSession = fyersModel.SessionModel(
        client_id=appId,
        redirect_uri=redirect_url,
        response_type=response_type,
        grant_type=grant_type,
        state="state",
        scope="",
        nonce=""
    )
    
    generateTokenUrl = appSession.generate_authcode()
    return generateTokenUrl

def extract_auth_code(url: str) -> str:
    """
    Extracts the auth code from the URL.
    The URL should be in the format: https://redirect_url?auth_code=AUTH_CODE
    """
    if "auth_code=" in url:
        return url.split("auth_code=")[1].split("&")[0]
    else:
        raise ValueError("Auth code not found in the URL.")

def get_refresh_token(auth_code: str) -> str:
    """
    Generates the access token using the auth code.
    """
    response_type = "code" 
    grant_type = "authorization_code" 
    session = fyersModel.SessionModel(
        client_id=appId,
        secret_key=app_secret, 
        redirect_uri=redirect_url, 
        response_type=response_type, 
        grant_type=grant_type
    )

    session.set_token(auth_code)

    response = session.generate_token()

    return response['refresh_token']
    

async def post_init(application: Application) -> None:
    """
    This function runs once after the bot has started.
    It sends the initial message to the target user.
    """
    auth_url = get_auth_token()
    try:
        await application.bot.send_message(
            chat_id=TARGET_USER_ID,
            text=f"Hello! Please log in using the following link: {auth_url}"
        )
        print(f"Initial message sent to user ID {TARGET_USER_ID}.")
    except Exception as e:
        logger.error(f"Failed to send initial message to {TARGET_USER_ID}: {e}")
        print("\n---")
        print(f"Error: Could not send message to USER_ID {TARGET_USER_ID}.")
        print("Please check two things:")
        print("1. Is the BOT_TOKEN correct?")
        print("2. Have you, the user, started a chat with your bot at least once before?")
        print("   (A user must interact with the bot first before the bot can message them.)")
        print("---\n")


def upload_to_gcs(local_file_path: str, bucket_name: str, blob_name: str):
    """
    Uploads a local file to a GCS bucket.
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_file_path)
    print(f"--> Response successfully uploaded to GCS: gs://{bucket_name}/{blob_name}")


async def log_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Receives the user's response, saves it to a file, and prints it."""
    user = update.effective_user
    user_response = update.message.text

    auth_code = extract_auth_code(user_response)  # Extract auth code from the user's response
    refresh_token = get_refresh_token(auth_code)  # Generate refresh token using the auth code
    
    # Get the timestamp from the message for accurate logging
    timestamp = update.message.date.strftime('%Y-%m-%d %H:%M:%S')

    # Create a formatted string to print and save
    log_entry = f"[{timestamp}] User '{user.first_name}' (ID: {user.id}) #REFRESH_TOKEN# {refresh_token}\n"

    # 1. Print the captured response to your console
    print(log_entry.strip())

    # 2. Save the response to a text file
    try:
        # 'a' stands for 'append mode', which adds the new line without overwriting the file
        with open("bot_responses.txt", "a", encoding="utf-8") as f:
            f.write(log_entry)
        print("--> Response successfully saved to bot_responses.txt")
        # Upload to GCS after saving locally
        upload_to_gcs("bot_responses.txt", GCS_BUCKET_NAME, REFRESH_TOKEN_FILE_PATH)
    except Exception as e:
        print(f"--> Error: Could not save response to file or upload to GCS. {e}")

    # 3. Send a confirmation message back to the user
    await update.message.reply_text("Thanks! I've logged your response.")
    sys.exit(0)  # Exit the program after logging the response


def main() -> None:
    """Set up and run the bot."""
    print("Starting bot...")

    # Create the Application instance with the post_init function
    builder = Application.builder().token(BOT_TOKEN)
    builder.post_init(post_init)
    application = builder.build()

    # Set up the MessageHandler to listen only for the target user's messages
    user_filter = filters.User(user_id=TARGET_USER_ID)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, log_response))

    # Start the bot
    print("Bot is running and waiting for a response...")
    application.run_polling()


if __name__ == "__main__":
    main()