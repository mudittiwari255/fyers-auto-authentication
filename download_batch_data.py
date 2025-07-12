import datetime
import pandas as pd
from fyers_apiv3 import fyersModel
import gcsfs
import time
import logging
import requests
import json

from credentials.credentials import appId, app_secret, redirect_url, TARGET_USER_ID, BOT_TOKEN, PIN
from config import GCS_BUCKET_NAME, REFRESH_TOKEN_FILE_PATH, GCS_RAW_FOLDER_PATH, TICKS, DAYS_TO_FETCH

import os
import hashlib

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "credentials/smr-v3-creds.json"

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logging.info(f"Total stock tickers to fetch: {len(TICKS)}")

def get_ssha256_hash(input_string):
    """Generate SHA256 hash of the input string."""
    sha_signature = hashlib.sha256(input_string.encode()).hexdigest()
    return sha_signature


def get_refresh_token_from_gcs():
    FULL_REFRESH_TOKEN_FILE_PATH = f"gs://{GCS_BUCKET_NAME}/{REFRESH_TOKEN_FILE_PATH}"
    try:
        gcs = gcsfs.GCSFileSystem()
        if gcs.exists(FULL_REFRESH_TOKEN_FILE_PATH):
            with gcs.open(FULL_REFRESH_TOKEN_FILE_PATH, 'r') as f:
                refresh_token = f.readlines()[-1].split('#REFRESH_TOKEN#')[-1].strip()
            logging.info("refresh token fetched successfully from GCS.")
            return refresh_token
        else:
            logging.error(f"refresh token file not found in GCS at {FULL_REFRESH_TOKEN_FILE_PATH}.")
            return ""
    except Exception as e:
        logging.error(f"Error fetching refresh token from GCS: {e}")
        return ""

def get_access_token(refresh_token):
    """
    Generates the access token using the refresh token.
    """
    url = 'https://api-t1.fyers.in/api/v3/validate-refresh-token'

    headers = {
        'Content-Type': 'application/json'
    }

    appIDHash = get_ssha256_hash(appId + ":" + app_secret)

    data = {
        "grant_type": "refresh_token",
        "appIdHash": appIDHash,
        "refresh_token": refresh_token,
        "pin": PIN 
    }

    try:    
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)

        # Parse the JSON response
        response_data = response.json()

        # You can access specific fields like this:
        if response_data.get("s") == "ok":
            access_token = response_data.get("access_token")
        
        return access_token
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching access token: {e}")
        return None
    

refresh_token = get_refresh_token_from_gcs()
if not refresh_token:
    logging.error("refresh token is empty. Please generate a valid refresh token.")
    exit(1)

access_token = get_access_token(refresh_token)
if not access_token:
    logging.error("Failed to fetch access token using the refresh token.")
    exit(1)

logging.info(f"Using access token: {access_token}")

fyers = fyersModel.FyersModel(client_id=appId, is_async=False, token=access_token)

def get_historical_data(symbol, resolution='D', date_format="1", range_from="None", range_to="None", cont_flag="1"):
    symbol = "NSE:" + symbol.upper() + "-EQ"

    data = {
        "symbol": symbol,
        "resolution": resolution,
        "date_format": date_format,
        "range_from": str(range_from), # Convert dates to string for the API call
        "range_to": str(range_to),
        "cont_flag": cont_flag
    }
    
    try:
        response = fyers.history(data=data)
        return response
    except Exception as e:
        logging.error(f"Error fetching data for {symbol}: {e}")
        return None

def fetch_and_export_to_gcs(tickers, bucket_path):
    """
    Fetches data for a list of tickers, deletes existing date partitions in GCS
    for the fetched dates, and then writes the new data.
    """
    all_data_frames = []

    range_to = datetime.date.today()
    range_from = range_to - datetime.timedelta(days=DAYS_TO_FETCH)
    logging.info(f"Fetching data from {range_from} to {range_to}...")

    logging.info(f"Starting data fetch for {len(tickers)} tickers...")

    for ticker in tickers:
        time.sleep(0.5)  # To avoid hitting API rate limits
        logging.info(f"Fetching data for {ticker}...")
        hist_data = get_historical_data(symbol=ticker, range_from=range_from, range_to=range_to)

        if hist_data and hist_data.get('s') == 'ok' and hist_data.get('candles'):
            df = pd.DataFrame(hist_data['candles'])
            df['symbol'] = ticker
            df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'symbol']
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
            df['date'] = df['datetime'].dt.date
            df['fetched_at'] = datetime.datetime.now()
            all_data_frames.append(df)
        else:
            logging.warning(f"Could not retrieve valid data for {ticker}. Response: {hist_data}")

    if not all_data_frames:
        logging.warning("No data was fetched. Exiting.")
        return

    master_df = pd.concat(all_data_frames, ignore_index=True)
    master_df = master_df[['date', 'symbol', 'open', 'high', 'low', 'close', 'volume', 'datetime', 'timestamp']]

    logging.info("Master DataFrame created. Ready for GCS export.")
    logging.info(f"\n{master_df.head()}")

    # --- NEW: Overwrite Logic ---
    # 1. Initialize GCS a filesystem object
    gcs = gcsfs.GCSFileSystem()

    # 2. Get the unique dates that will be written
    dates_to_write = master_df['date'].unique()

    logging.info("Checking for existing partitions in GCS to overwrite...")
    for date_obj in dates_to_write:
        # The partition folder format is 'key=value', e.g., 'date=2025-06-14'
        partition_folder = f"date={date_obj}"
        full_partition_path = f"{bucket_path}/{partition_folder}"

        logging.info(f"  - Checking partition for date: {date_obj} at {full_partition_path}")

        # 3. Check if the partition directory exists
        if gcs.exists(full_partition_path):
            logging.info(f"  - Partition for {date_obj} found. Deleting: {full_partition_path}")
            # 4. If it exists, delete it recursively
            gcs.rm(full_partition_path, recursive=True)
        else:
            logging.info(f"  - Partition for {date_obj} not found. A new one will be created.")
    
    # --- END of new logic ---

    logging.info(f"Exporting data to GCS bucket: {bucket_path} partitioned by 'date'...")
    try:
        master_df.to_parquet(
            path=bucket_path,
            engine='pyarrow',
            partition_cols=['date'],
            index=False
        )
        logging.info("Export to GCS successful! ✅")
    except Exception as e:
        logging.error(f"Failed to export to GCS. Error: {e} ❌")


# --- Execute the Process ---

if __name__ == "__main__":
    # Construct the full GCS path
    full_gcs_path = f"gs://{GCS_BUCKET_NAME}/{GCS_RAW_FOLDER_PATH}"
    
    fetch_and_export_to_gcs(
        tickers=TICKS,
        bucket_path=full_gcs_path
    )