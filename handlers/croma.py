import re
import logging
from pathlib import Path
from base_handler import BaseHandler


logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).parent / "prompts" / "croma.txt"


class CromaHandler(BaseHandler):

    def __init__(self):
        super().__init__()
        self._prompt = PROMPT_PATH.read_text(encoding="utf-8")

    @property
    def company_name(self):
        return "Infiniti Retail Limited"
    
    @property
    def portal_name(self):
        return "Infiniti"
    
    @property
    def reference_sheet(self):
        return "Croma_Details"

    
    @property
    def text_end_marker(self):
        return "This is system generated"
    
    @property
    def text_start_marker(self) -> str:
        # Items table always follows this line
        return "PLEASE SUPPLY IN GOOD ORDER AND CONDITION"
    

    def identify(self, full_text: str):
        return 'infiniti retail limited' in full_text.lower()
    

    def extract_metadata(self, full_text: str, pdf_path: str):
        """
        Output: (DC code, PO number)
        """
        try:

            # Extract DC code and PO number using regex
            dc_match  = re.search(r"\bD\d{3}\b", full_text)
            po_match  = re.search(r"PURCHASE\s*ORDER\s*:?\s*(\d+)", full_text)
    
            dc_code = dc_match.group(0)  if dc_match else ""
            po_num  = po_match.group(1)  if po_match else ""

            if not dc_code:
                logger.warning(f"No DC code found in: {pdf_path}")
                return "", ""

            if not po_num:
                logger.warning(f"No PO number found in: {pdf_path}")
                return "", ""
            
            logger.info(f"DC code: {dc_code}, PO number: {po_num}")

            return dc_code, po_num
        
        except Exception as e:
            logger.error(f"Error extracting DC or PO Number: {pdf_path} — {e}", exc_info=True)
            return "", ""
