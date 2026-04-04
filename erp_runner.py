import os
import time
import subprocess
import logging


logger = logging.getLogger(__name__)


def upload_to_erp(bw_exe: str, bwc_file: str, session: str, csv_path: str, excel_output_path: str) -> bool:
    """
    Runs the Infor BW ERP session via subprocess.
 
    Equivalent to running:
        bw.exe "Test.bwc" -- tdkro8250m001 "output.csv"
 
    Returns True on success, False on failure.
    """

    if not all(os.path.exists(f) for f in [bw_exe, bwc_file, csv_path]):
        logger.error("Required files (BW EXE, BWC, or CSV) are missing.")
        return False

    if os.path.exists(excel_output_path):
        try:
            os.remove(excel_output_path)
            logger.info(f"Deleted old report: {excel_output_path}")
        except Exception as e:
            logger.error(f"Could not delete old file (is it open in Excel?): {e}")
            return False

    command = [
        bw_exe, 
        bwc_file,
        "-nodebug",
        "--", 
        session, 
        csv_path, 
        excel_output_path
    ]

    logger.info(f"Starting ERP session: {session}")
    logger.debug(f"Command: {' '.join(command)}")

    try:
        result = subprocess.run(
            command,
            check=True,
            timeout=300
        )

        time.sleep(5) 

        if os.path.exists(excel_output_path):
            logger.info("Success: Excel report generated.")
            return True
        else:
            logger.error("ERP finished but Excel file was not found.")
            return False
 
    except subprocess.TimeoutExpired:
        logger.error("ERP Session timed out after 5 minutes.")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"ERP failed with exit code {e.returncode}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return False
