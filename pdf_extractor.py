import pandas as pd
import pdfplumber
import logging
from handlers import HANDLERS


logger = logging.getLogger(__name__)   


def extract_full_text(pdf_path: str) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(
            page.extract_text() or "" for page in pdf.pages
        )


def extract_data(pdf_path: str, api_key: str) -> tuple:
    """
    Extract data from a PDF file using one of the registered handlers.

    Parameters:
    pdf_path (str): Path to the PDF file.
    api_key (str): API key for LLM API.

    Returns:
    tuple: (dc_code, po_num, df, handler)
    dc_code (str): DC code
    po_num (str): PO number
    df (pd.DataFrame): Items table extracted from the PDF
    handler (BaseHandler): The handler that matched the PDF
    """
    full_text = extract_full_text(pdf_path)

    if not full_text.strip():
        logger.warning(f"No text found in PDF: {pdf_path}")
        return "", "", pd.DataFrame(), None

    for handler in HANDLERS:
        if handler.identify(full_text):
            dc_code, po_num = handler.extract_metadata(full_text, pdf_path)
            if not dc_code or not po_num:
                logger.warning(f"Metadata extraction failed for: {pdf_path}")
                return "", "", pd.DataFrame(), None
            df = handler.extract_table(pdf_path, full_text, api_key)
            return dc_code, po_num, df, handler 
    
    logger.error(f"No handler matched for: {pdf_path}")
    return "", "", pd.DataFrame(), None