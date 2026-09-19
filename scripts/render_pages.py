import os
import win32com.client
import fitz # PyMuPDF

def convert_and_render():
    docx_p = r"c:\Users\DCALL\Desktop\gecko\output\resumes\Dave-Call+cc58e632010a4e20.docx"
    pdf_p = r"c:\Users\DCALL\Desktop\gecko\scratch\preview.pdf"
    
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(os.path.abspath(docx_p))
        doc.SaveAs(os.path.abspath(pdf_p), FileFormat=17)
        doc.Close(False)
    finally:
        word.Quit()
    
    doc = fitz.open(pdf_p)
    print(f"PDF Page count: {len(doc)}")
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=150)
        img_path = f"c:\\Users\\DCALL\\Desktop\\gecko\\scratch\\page_{i+1}.png"
        pix.save(img_path)
        print(f"Saved {img_path}")

if __name__ == "__main__":
    convert_and_render()
