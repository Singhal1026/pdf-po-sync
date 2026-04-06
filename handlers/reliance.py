import re
import logging
from pathlib import Path
from base_handler import BaseHandler


logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).parent / "prompts" / "reliance.txt"

class RelianceHandler(BaseHandler):

    def __init__(self):
        super().__init__()
        self._prompt = PROMPT_PATH.read_text(encoding="utf-8")

    @property
    def company_name(self):
        return "Reliance Retail Limited"
    
    @property
    def portal_name(self):
        return "Reliance"
    
    @property
    def reference_sheet(self):
        return "Reliance_Details"


    @property
    def text_end_marker(self):
        return "Terms of payment :"
    
    @property
    def text_start_marker(self) -> str:
        # Items table always follows this line
        return "Signature"
    
    
    def identify(self, full_text: str):
        return 'reliance retail limited' in full_text.lower()
    
    def extract_metadata(self, full_text: str, pdf_path: str):
        """
        Output: (Site code, PO number)
        """
        try:

            # Extract DC code and PO number using regex
            po_site_match = re.search(
                r"PO\s*NO\.?\s*:\s*(\d+).*?Site\s*:\s*([A-Za-z0-9]{4})",
                full_text,
                re.IGNORECASE | re.DOTALL
            )
    
            site_code = po_site_match.group(2)  if po_site_match else ""
            po_num  = po_site_match.group(1)  if po_site_match else ""

            if not site_code:
                logger.warning(f"No Site code found in: {pdf_path}")
                return "", ""

            if not po_num:
                logger.warning(f"No PO number found in: {pdf_path}")
                return "", ""
            
            return site_code, po_num
        
        except Exception as e:
            logger.error(f"Error extracting DC or PO Number: {pdf_path} — {e}", exc_info=True)
            return "", ""
