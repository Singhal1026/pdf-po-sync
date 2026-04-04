import os
import sys
import shutil
import configparser
import pandas as pd
from typing import List
from datetime import datetime

from logger import setup_logger
from pdf_extractor import extract_data
from erp_runner import upload_to_erp
import logging


if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config():
    """Loads configuration from config.ini in the same directory as the script/executable."""
    config = configparser.ConfigParser()
    config_path = os.path.join(BASE_DIR, "config.ini")
    if not config.read(config_path):
        raise FileNotFoundError(f"config.ini not found at: {config_path}")
    return config


def resolve_path(config: configparser.ConfigParser, section: str, key: str):
    """Returns absolute path — joins BASE_DIR if path is relative."""
    raw_path = config.get(section, key)
    if os.path.isabs(raw_path):
        return raw_path
    return os.path.join(BASE_DIR, raw_path)


def copy_pdf_to_working_dir(drive_path: str, input_dir: str) -> List[str]:
    """
    Copies all PDFs from the shared drive to local input_dir.
    Returns list of copied filenames.
    """
    os.makedirs(input_dir, exist_ok=True)
    copied = []

    if not os.path.exists(drive_path):
        logger.error(f"Shared drive path not accessible: {drive_path}")
        return []

    for filename in os.listdir(drive_path):
        if filename.lower().endswith('.pdf'):
            src = os.path.join(drive_path, filename)
            dst = os.path.join(input_dir, filename)
            try:
                shutil.copy2(src, dst)
                copied.append(filename)
                logger.info(f"Copied from Shared Drive: {filename}")
            except Exception as e:
                logger.error(f"Failed to copy {filename} from shared drive: {e}")
            
    logger.info(f"Copied {len(copied)} PDF(s) from shared drive")
    return copied

def cleanup_input(input_dir: str) -> None:
    """Deletes all PDFs from local input folder after processing."""
    for filename in os.listdir(input_dir):
        if filename.lower().endswith(".pdf"):
            try:
                os.remove(os.path.join(input_dir, filename))
                logger.debug(f"Deleted from input: {filename}")
            except Exception as e:
                logger.warning(f"Could not delete {filename} from input: {e}")

    logger.info("Input directory cleaned up")


def run() -> None:
    
    start_time = datetime.now()

    config = load_config()

    shared_drive_path = config.get('paths', 'shared_drive_path')
    input_dir = resolve_path(config, 'paths', 'input_dir')
    output_csv = resolve_path(config, 'paths', 'output_csv')
    ref_path = resolve_path(config, 'paths', 'reference_xlsx')
    excel_output_path = resolve_path(config, 'paths', 'excel_output_path')
    upload_in_erp = config.getboolean('erp', 'upload_in_erp')


    if not os.path.exists(shared_drive_path):
        logger.error(f"Shared drive path does not exist: {shared_drive_path}")
        return

    # ERP config — bw_exe and bwc_file are always absolute (system paths)
    bw_exe   = config.get("erp", "bw_exe")
    bwc_file = config.get("erp", "bwc_file")
    session  = config.get("erp", "session")
    gemini_api_key = config.get("llm", "gemini_api_key")
    groq_api_key = config.get("llm", "groq_api_key")

    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(os.path.dirname(output_csv),  exist_ok=True)

    logger.info(f"Shared drive path: {shared_drive_path}")
    logger.info(f"Input directory: {input_dir}")
    logger.info(f"Output directory: {os.path.dirname(output_csv)}")
    
    cleanup_input(input_dir)

    # ── Step 1: Copy PDFs from shared drive ─────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"Pipeline started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    copy_pdf_to_working_dir(shared_drive_path, input_dir)

    pdf_files = [
        f for f in os.listdir(input_dir) 
        if f.lower().endswith('.pdf') and os.path.isfile(os.path.join(input_dir, f))
    ]

    if not pdf_files:
        logger.info("No PDF files found to process. Exiting.")
        return

    logger.info(f"Found {len(pdf_files)} PDF(s) to process")


    # ── Step 2: Process each PDF ─────────────────────────────────────────────
    all_results = []
    stats = {"success": 0, "skipped": 0, "failed": 0}

    for pdf_file in pdf_files:
        pdf_path = os.path.join(input_dir, pdf_file)
        logger.info(f"Processing: {pdf_file}")

        try:
            # Stage 1: Extract text
            dc_code, po_num, extracted_table, handler = extract_data(pdf_path, groq_api_key)

            if handler is None:
                logger.warning(f"Skipping {pdf_file}: could not match to any known company")
                stats["skipped"] += 1
                continue
            
            if not dc_code or not po_num or extracted_table.empty:
                logger.warning(f"Skipping {pdf_file}: could not extract DC code or table or po_num")
                stats["skipped"] += 1
                continue
            
            logger.info(f"Extracted DC Code: {dc_code}, PO Number: {po_num} from {pdf_file}")

            # Stage 2: Preprocess
            preprocessed_df = handler.preprocess(extracted_table, po_num, dc_code, ref_path)
            
            if preprocessed_df is None or preprocessed_df.empty:
                logger.warning(f"Skipping {pdf_file}: no valid items after preprocessing")
                stats["skipped"] += 1
                continue

            logger.info(f"Preprocessed data for {pdf_file}")
            
            all_results.append({"filename": pdf_file, "df": preprocessed_df})
            logger.info(f"{pdf_file} — ready for upload ({len(preprocessed_df)} row(s))")

        except Exception as e:
            logger.error(f"Unexpected error processing {pdf_file}: {e}", exc_info=True)
            stats["failed"] += 1

    # ── Step 3: Upload all good PDFs in one single DB transaction ───────────
    if not all_results:
        logger.warning("No valid PDFs to upload. Exiting.")
        logger.info(f"Summary — Skipped: {stats['skipped']} | Failed: {stats['failed']}")
        return
    
    logger.info(f"{len(all_results)} PDF(s) passed all checks — uploading to ERP Session...")
    
    final_df = pd.concat([item['df'] for item in all_results], ignore_index=True)
    final_df.to_csv(output_csv, index=False)
    # print(final_df)
    logger.info(f"Output CSV saved: {output_csv} ({len(final_df)} total rows)")
    # stats["success"] = len(all_results)

    if upload_in_erp and upload_to_erp(bw_exe, bwc_file, session, output_csv, excel_output_path):
        stats["success"] = len(all_results)
        logger.info("All data uploaded to ERP Session successfully.")

        
        # ── Step 4: Cleanup local input folder ───────────────────────────────
        if config.getboolean("pipeline", "delete_local_input_after_processing"):
            cleanup_input(input_dir)
            logger.info("Local input folder cleared")
        
        
        # ── Step 5: Optionally delete from shared drive ─────────────────────
        delete_from_drive = config.getboolean('pipeline', 'delete_from_shared_drive_after_copy')

        if delete_from_drive:
            for item in all_results:
                pdf_file = item['filename']
                drive_file_path = os.path.join(shared_drive_path, pdf_file)
                if os.path.exists(drive_file_path):
                    try:
                        os.remove(drive_file_path)
                        logger.info(f"Deleted from shared drive: {pdf_file}")
                    except Exception as e:
                        logger.error(f"Failed to delete from shared drive: {pdf_file} — {e}")

    else:
        if not upload_in_erp:
            logger.info("Skipping ERP upload as per configuration.")
        else:
            logger.error("DB upload failed for all data.")
            stats["failed"] += len(all_results)

    # ── Summary ──────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(
        f"Pipeline finished — "
        f"Total PDFs processed: {len(all_results)} | "
        f"Uploaded: {stats['success']} | "
        f"Skipped: {stats['skipped']} | "
        f"Failed: {stats['failed']}"
    )
    logger.info("=" * 60)

    logger.info(f"Pipeline runtime: {datetime.now() - start_time}")


if __name__ == "__main__":
    config = load_config()
    log_file = resolve_path(config, "paths", "log_file")
    setup_logger(log_file)

    logger = logging.getLogger(__name__)
    logger.info("--- Pipeline Session Started ---")
    run()
    logger.info("--- Pipeline Session Finished ---")