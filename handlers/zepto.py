import re
import time
import logging
import pandas as pd
from pathlib import Path
from llm_client import call_llm, call_groq
from base_handler import BaseHandler

PROMPT_PATH = Path(__file__).parent / "prompts" / "zepto.txt"
logger = logging.getLogger(__name__)


class ZeptoHandler(BaseHandler):

    def __init__(self):
        self._df_ref = None
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
    
    def extract_table(self, pdf_path:str, full_text: str, api_key: str) -> pd.DataFrame:
        """
        Extract the items table from the PDF using LLM.
        
        Parameters:
        pdf_path (str): Path to the PDF file.
        full_text (str): Full text of the PDF file.
        api_key (str): API key for LLM API.
        
        Returns:
        pd.DataFrame: The extracted items table with the Article Code, Qty and Price.
        """

        split_text_1 = "Total Taxable Amount"
        split_text_2 = "Shipping Address"

        lower_text = full_text.lower()

        if split_text_1.lower() in lower_text:
            full_text = re.split(re.escape(split_text_1), full_text, flags=re.IGNORECASE)[0]
        if split_text_2.lower() in lower_text:
            full_text = re.split(re.escape(split_text_2), full_text, flags=re.IGNORECASE)[-1]

        time.sleep(2)  
        rows = call_groq(self._prompt, full_text, api_key)

        if not rows.get("items"):
            logger.warning(f"No table data extracted by LLM for PDF: {pdf_path}")
            return pd.DataFrame()

        df = pd.DataFrame(rows.get('items', []))

        if df.empty:
            logger.warning(f"Empty DataFrame for PDF: {pdf_path}")
            return df

        df['Qty']   = pd.to_numeric(df['Qty'],   errors='coerce')
        df['Price'] = pd.to_numeric(df['Price'],  errors='coerce')
        df = df.dropna(subset=['Qty', 'Price']).reset_index(drop=True)
        # save dataframe to csv for debugging
        # df.to_csv(f"{pdf_path.stem}_extracted.csv", index=False)

        logger.info(f"LLM extracted {len(df)} rows for Croma")
        return df
        

    def preprocess(self, items, po_num, dc_code, ref_path):
        
        """
        Preprocess the items dataframe by merging it with the reference dataframe.
        
        Parameters:
        items (pd.DataFrame): Items dataframe containing the article code, quantity and price.
        po_num (str): Purchase order number.
        dc_code (str): DC code.
        df_ref (pd.DataFrame): Reference dataframe containing the article code, KENT SKU, BP CODE and Address Code.
        
        Returns:
        pd.DataFrame: The final preprocessed dataframe containing the required columns for the ERP upload.
        """

        if self._df_ref is None:
            self._df_ref = pd.read_excel(ref_path, sheet_name=self.reference_sheet, dtype=object)
            logger.info(f"Loaded refernece sheet: {self.reference_sheet}")

        items["po_num"] = po_num
        items["dc_code"] = dc_code

        items['Article Code'] = items['Article Code'].astype(str).str.strip()
        self._df_ref['Article code'] = self._df_ref['Article code'].astype(str).str.strip()

        merged_df = pd.merge(
            items,
            self._df_ref,
            left_on='Article Code',
            right_on='Article code',
            how='left'
        )

        merged_df = merged_df[['Qty', 'Price', 'po_num', 'dc_code', 'KENT SKU']]

        final_merged = pd.merge(
            merged_df, 
            self._df_ref, 
            left_on='dc_code', 
            right_on='facility_name 2',
            how='left'
        )

        final_merged['Portal'] = self.portal_name
        final_merged['Customer Name'] = self.company_name

        final_merged['Qty'] = final_merged['Qty'].fillna(0)
        final_merged['Price'] = final_merged['Price'].fillna(0)

        str_cols = ['Portal', 'Customer Name', 'BP CODE', 'Address Code']
        final_merged[str_cols] = final_merged[str_cols].fillna("")

        try:
            final_merged = final_merged[[
                'Portal', 
                'po_num',       
                'BP CODE', 
                'Address Code', 
                'KENT SKU_x', 
                'Qty', 
                'Price', 
                'Emp Code', 
                'Customer Name', 
                'W/H Code'
            ]]

            return final_merged
        except KeyError as e:
            logger.error(f"Mapping failed for PO {po_num}. Missing column in Reference Excel: {e}")
            return pd.DataFrame()
