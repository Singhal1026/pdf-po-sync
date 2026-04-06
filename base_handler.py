import re
import time
import logging
import pandas as pd
from abc import ABC, abstractmethod
from typing import Tuple


logger = logging.getLogger(__name__)


class BaseHandler(ABC):

    def __init__(self):
        self._df_ref = None

    @abstractmethod
    def identify(self, full_text: str) -> bool:
        """Return True if this handler owns the PDF"""
        ...


    @abstractmethod
    def extract_metadata(self, full_text: str, pdf_path: str) -> Tuple[str, str]:
        """Return (site_code/dc_code, po_number)."""
        ...


    @property
    @abstractmethod
    def company_name(self) -> str:
        """Human-readable company name, e.g. 'Infiniti Retail Limited'"""
        ...

    
    @property
    @abstractmethod
    def portal_name(self) -> str:
        """Portal label used in ERP output, e.g. 'Infiniti'"""
        ...


    @property
    @abstractmethod
    def reference_sheet(self) -> str:
        """Sheet name in RC_Portal_Details.xlsx for this vendor."""
        ...


    @property
    @abstractmethod
    def text_end_marker(self) -> str:
        """
        Phrase that marks the END of useful content.
        Everything after this phrase is discarded.
        Example: 'This is system generated'
        Return '' to skip tail-trimming.
        """
        ...
 
    @property
    @abstractmethod
    def text_start_marker(self) -> str:
        """
        Phrase that marks the START of useful content.
        Everything before this phrase is discarded.
        Example: 'PLEASE SUPPLY IN GOOD ORDER AND CONDITION'
        Return '' to skip head-trimming.
        """
        ...


    def _call_llm(self, full_text: str, api_key: str) -> dict:
        """
        Call the LLM with this handler's prompt.
        Override this method to swap the LLM backend for a specific vendor.
        """
        from llm_client import call_groq
        return call_groq(self._prompt, full_text, api_key)

    
    def extract_table(self, pdf_path: str, full_text: str, api_key: str) -> pd.DataFrame:
        """
        Trim the raw PDF text using vendor-specific markers, call the LLM,
        and return a clean DataFrame with columns [Article Code, Qty, Price].
 
        Subclasses control trimming via text_end_marker / text_start_marker.
        Override _call_llm() to use a different LLM backend.
        """

        lower_text = full_text.lower()
 
        if self.text_end_marker and self.text_end_marker.lower() in lower_text:
            full_text = re.split(
                re.escape(self.text_end_marker), full_text, flags=re.IGNORECASE
            )[0]
 
        if self.text_start_marker and self.text_start_marker.lower() in lower_text:
            full_text = re.split(
                re.escape(self.text_start_marker), full_text, flags=re.IGNORECASE
            )[-1]
 
        # time.sleep(5)
        rows = self._call_llm(full_text, api_key)
 
        if not rows.get("items"):
            logger.warning(f"No table data extracted by LLM for PDF: {pdf_path}")
            return pd.DataFrame()
 
        df = pd.DataFrame(rows["items"])
 
        if df.empty:
            logger.warning(f"Empty DataFrame for PDF: {pdf_path}")
            return df
 
        df["Qty"]   = pd.to_numeric(df["Qty"],   errors="coerce")
        df["Price"] = pd.to_numeric(df["Price"],  errors="coerce")
        df = df.dropna(subset=["Qty", "Price"]).reset_index(drop=True)
 
        logger.info(f"LLM extracted {len(df)} rows for {self.company_name}")
        return df


    def preprocess(self, items: pd.DataFrame, po_num: str, dc_code: str, ref_path: str) -> pd.DataFrame:
        """
        Merge extracted items against the reference sheet and return an
        ERP-ready DataFrame.
 
        Merge strategy:
          1. Join items → ref on Article Code  (gets KENT SKU per line item)
          2. Join result → ref on dc_code / facility_name 2  (gets site metadata)
        """
        try:
            if self._df_ref is None:
                self._df_ref = pd.read_excel(
                    ref_path, sheet_name=self.reference_sheet, dtype=object
                )
                logger.info(f"Loaded reference sheet: {self.reference_sheet}")
 
            items = items.copy()
            items["po_num"]  = po_num
            items["dc_code"] = dc_code
 
            items["Article Code"]         = items["Article Code"].astype(str).str.strip()
            self._df_ref["Article code"]  = self._df_ref["Article code"].astype(str).str.strip()
 
            # Join 1 — article code → KENT SKU
            merged_df = pd.merge(
                items,
                self._df_ref,
                left_on="Article Code",
                right_on="Article code",
                how="left",
            )
            merged_df = merged_df[["Qty", "Price", "po_num", "dc_code", "KENT SKU"]]
 
            # Join 2 — dc_code → site metadata
            final_merged = pd.merge(
                merged_df,
                self._df_ref,
                left_on="dc_code",
                right_on="facility_name 2",
                how="left",
            )
 
            final_merged["Portal"]        = self.portal_name
            final_merged["Customer Name"] = self.company_name
 
            final_merged["Qty"]   = final_merged["Qty"].fillna(0)
            final_merged["Price"] = final_merged["Price"].fillna(0)
 
            str_cols = ["Portal", "Customer Name", "BP CODE", "Address Code"]
            final_merged[str_cols] = final_merged[str_cols].fillna("")
 
            return final_merged[[
                "Portal",
                "po_num",
                "BP CODE",
                "Address Code",
                "KENT SKU_x",
                "Qty",
                "Price",
                "Emp Code",
                "Customer Name",
                "W/H Code",
            ]]
 
        except KeyError as e:
            logger.error(
                f"Mapping failed for PO {po_num}. Missing column in Reference Excel: {e}"
            )
            return pd.DataFrame()
        except Exception as e:
            logger.error(
                f"Error preprocessing data for PO {po_num} — {e}", exc_info=True
            )
            return pd.DataFrame()
