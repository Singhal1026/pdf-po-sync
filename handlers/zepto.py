import re
import logging
from pathlib import Path
from base_handler import BaseHandler

PROMPT_PATH = Path(__file__).parent / "prompts" / "zepto.txt"
logger = logging.getLogger(__name__)


class ZeptoHandler(BaseHandler):

    def __init__(self):
        super().__init__()
        self._prompt = PROMPT_PATH.read_text(encoding="utf-8")

    @property
    def company_name(self):
        return "Zepto Private Limited"
    
    @property
    def portal_name(self):
        return "Zepto"
    
    @property
    def reference_sheet(self):
        return "Zepto_Details"
    

    @property
    def text_end_marker(self):
        return "Total Taxable Amount"
    
    @property
    def text_start_marker(self) -> str:
        # Items table always follows this line
        return "Shipping Address"
    
    
    def identify(self, full_text: str):
        return 'zepto private limited' in full_text.lower()
    
    def extract_metadata(self, full_text: str, pdf_path: str):
        """
        Output: (DC code, PO number)
        """

        possible_dc_codes = ['GUR044M', 'BLR135M', 'MUM175M', 'CHN063M']

        try:

            # Extract DC code and PO number using regex
            dc_code = next((code for code in possible_dc_codes if code.lower() in full_text.lower()), "")
            
            po_match = re.search(r"PO\s*No[:\s]*([Pp]\d+)", full_text)
    
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
    
