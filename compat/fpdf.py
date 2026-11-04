"""Very small PDF writer shim for ``fpdf`` (used by the pydfnworks report).

Implements the small subset of the ``FPDF`` API that
``pydfnworks/dfnGen/generation/output_report/make_pdf.py`` uses, producing a
simple valid PDF (one page, Helvetica, plain text).  Install the real fpdf2
package for a nicer report.
"""


class FPDF:
    def __init__(self, *args, **kwargs):  # noqa: ARG002
        self.pages = []
        self._buf = []
        self.l_margin = 10
        self.t_margin = 10

    def add_page(self, orientation="P"):  # noqa: ARG002
        self._flush()
        self.pages.append([])

    def set_font(self, family="Helvetica", style="", size=12):  # noqa: ARG002
        self.font_size = size

    def _page(self):
        if not self.pages:
            self.pages.append([])
        return self.pages[-1]

    def _flush(self):
        if self._buf:
            self._page().append(" ".join(self._buf))
            self._buf = []

    def cell(self, w=0, h=0, txt="", ln=0, align="L"):  # noqa: ARG002
        if txt:
            self._buf.append(str(txt))
        if ln:
            self._flush()

    def multi_cell(self, w=0, h=0, txt=""):  # noqa: ARG002
        for line in str(txt).splitlines():
            self.pages and self._page().append(line)

    def ln(self, h=1):  # noqa: ARG002
        self._flush()

    def image(self, *args, **kwargs):  # noqa: ARG002
        pass  # image embedding is out of scope for the shim

    def output(self, name="", dest=""):
        self._flush()
        lines = [ln for page in self.pages for ln in page] or ["(empty report)"]
        content = []
        y = 780
        for line in lines[:60]:
            safe = (line or "").replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            content.append(f"BT /F1 11 Tf 72 {y} Td ({safe}) Tj ET")
            y -= 14
        stream = "\n".join(content).encode("latin-1", "replace")
        objs = []
        objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>")
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" +
                    stream + b"\nendstream")
        objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        out = bytearray(b"%PDF-1.4\n")
        offsets = []
        for i, obj in enumerate(objs, start=1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
        xref_pos = len(out)
        out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
        for off in offsets:
            out += f"{off:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\n"
                f"startxref\n{xref_pos}\n%%EOF").encode()
        with open(name, "wb") as fh:
            fh.write(bytes(out))
