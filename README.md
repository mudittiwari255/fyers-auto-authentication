# Fyers Auto-Authentication & Data Downloader

A Python-based solution to automate the Fyers API authentication process and download historical stock data. This project uses a Telegram bot for a one-time manual step to generate a long-lived refresh token, which is then used for fully automated daily data fetching. The data is stored efficiently in Google Cloud Storage (GCS).

## Features

-   **Automated Authentication**: Streamlines the Fyers V3 API authentication flow.
-   **Telegram Bot Integration**: Securely and interactively obtains the initial authorization code from the user.
-   **Refresh Token Management**: Generates and securely stores the refresh token in GCS, eliminating the need for daily manual logins.
-   **Batch Data Downloader**: Fetches historical daily candle data for a predefined list of stock tickers.
-   **Cloud Storage**: Saves data in Parquet format to GCS, partitioned by date for efficient querying and analysis.
-   **Idempotent Writes**: Automatically handles overwriting of existing data partitions to ensure data integrity and prevent duplication.

## How It Works

The system is composed of two main scripts:

1.  **`generate_referesh_token.py` (One-Time Setup)**
    -   This script starts a Telegram bot.
    -   The bot sends a Fyers login URL to a specified Telegram user ID.
    -   The user logs in, and Fyers redirects them to a URL containing an `auth_code`.
    -   The user pastes this redirect URL back into the Telegram chat.
    -   The script extracts the `auth_code`, exchanges it for a `refresh_token`, and securely uploads the token to a specified file in a GCS bucket.

2.  **`download_batch_data.py` (Automated/Scheduled Task)**
    -   This script is designed to be run on a schedule (e.g., daily cron job, Cloud Function).
    -   It fetches the latest `refresh_token` from GCS.
    -   It uses the `refresh_token` to generate a short-lived `access_token`.
    -   Using the `access_token`, it connects to the Fyers API and downloads historical data for the configured tickers.
    -   The fetched data is written to a GCS bucket in Parquet format, partitioned by `date`. If data for a specific date already exists, it is overwritten to ensure the data is up-to-date.

## Prerequisites

-   Python 3.8+
-   A Fyers Trading Account and API credentials (`appId`, `app_secret`).
-   A Google Cloud Platform (GCP) project with a GCS bucket.
-   A GCP service account with permissions to write to GCS.
-   A Telegram account and a Telegram Bot (`BOT_TOKEN`).

## Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/mudittiwari255/fyers-auto-authentication.git
    cd fyers-auto-authentication
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    -   Run `pip install -r requirements.txt`.


4.  **Configure GCP Credentials:**
    -   Download the JSON key file for your GCP service account.
    -   Place it in the `credentials/` directory. The code expects it at `credentials/smr-v3-creds.json`.

5.  **Configure Application Secrets:**
    -   Open `credentials/credentials.py` and fill in your details:
        ```python
        appId = "YOUR_FYERS_APP_ID"
        app_secret = "YOUR_FYERS_APP_SECRET"
        redirect_url = "YOUR_FYERS_REDIRECT_URL" # e.g., "https://www.google.com/"
        TARGET_USER_ID = 123456789 # Your numeric Telegram User ID
        BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
        PIN = "YOUR_FYERS_4_DIGIT_PIN"
        ```
    -   **To get your Telegram User ID:** Message `@userinfobot` on Telegram.

6.  **Configure Settings:**
    -   Open `config.py` and fill in your GCS and data fetching details. You will need to add the `TICKS` and `DAYS_TO_FETCH` variables.
        ```python
        GCS_BUCKET_NAME = "your-gcs-bucket-name"
        REFRESH_TOKEN_FILE_PATH = "fyers/auth/refresh_token.txt" # Path within the bucket to store the token
        GCS_RAW_FOLDER_PATH = "fyers/raw_data/daily_ticks" # Path within the bucket to store raw data
        TICKS = ["SBIN", "RELIANCE", "HDFCBANK"] # List of stock tickers to fetch
        DAYS_TO_FETCH = 90 # Number of past days of data to fetch
        ```

## Usage

1.  **Generate the Refresh Token (One-Time Step):**
    -   Run the `generate_referesh_token.py` script:
        ```bash
        python generate_referesh_token.py
        ```
    -   Check your Telegram. The bot will send you a login link.
    -   Click the link and log in to Fyers with your credentials.
    -   After logging in, you will be redirected. Copy the **entire** URL from your browser's address bar.
    -   Paste the URL back into the chat with your Telegram bot.
    -   The script will confirm that the token has been logged and uploaded to GCS. You can now stop the script (`Ctrl+C`).

2.  **Download Historical Data:**
    -   Run the `download_batch_data.py` script:
        ```bash
        python download_batch_data.py
        ```
    -   The script will use the token from GCS to authenticate and download the data for the tickers specified in `config.py`.
    -   This script is designed to be automated. You can set it up as a cron job or a serverless function (like GCP Cloud Functions or AWS Lambda) to run at a regular interval (e.g., daily after market close).

## Disclaimer

This project is for educational and personal use only. Trading in financial markets involves risk. The author is not responsible for any financial losses incurred using this software. Always handle your API keys and credentials securely and do not expose them in public repositories.