import os
import win32com.client
from pdf2image import convert_from_path

def docx_to_pdf(docx_path, pdf_path):
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(os.path.abspath(docx_path))
        doc.SaveAs(os.path.abspath(pdf_path), FileFormat=17) # 17 = wdFormatPDF
        doc.Close(False)
    finally:
        word.Quit()
    print(f"Converted {docx_path} to {pdf_path}")

def render_pdf_pages(pdf_path, output_dir):
    import pypdf
    reader = pypdf.PdfReader(pdf_path)
    print(f"Total pages in PDF: {len(reader.pages)}")
    return len(reader.pages)

if __name__ == "__main__":
    docx_p = r"c:\Users\DCALL\Desktop\gecko\output\resumes\Dave-Call+cc58e632010a4e20.docx"
    pdf_p = r"c:\Users\DCALL\Desktop\gecko\scratch\preview.pdf"
    docx_to_pdf(docx_p, pdf_p)
    pages = render_pdf_pages(pdf_p, r"c:\Users\DCALL\Desktop\gecko\scratch")
