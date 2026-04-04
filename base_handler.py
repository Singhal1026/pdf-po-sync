from abc import ABC, abstractmethod
from typing import Tuple
import pandas as pd


class BaseHandler(ABC):

    @abstractmethod
    def identify(self, full_text: str) -> bool:
        """Return True if this handler owns the PDF"""
        ...


    @abstractmethod
    def extract_metadata(self, full_text: str, pdf_path: str) -> Tuple[str, str]:
        """Return (site_code/dc_code, po_number)."""
        ...


    @abstractmethod
    def extract_table(self, pfd_path: str, full_text: str, api_key: str) -> pd.DataFrame:
        """Extract the items table from the PDF."""
        ...

    
    @abstractmethod
    def preprocess(self, item: pd.DataFrame, po_num: str, dc_code: str, df_ref: pd.DataFrame) -> pd.DataFrame:
        """Return the final ERP-ready DataFrame."""
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
        """Sheet name in RC_Portal_Details.xlsx to load for this company."""
        ...


