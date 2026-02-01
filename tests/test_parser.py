"""Tests for services/parser.py - Document parsing functionality."""

import io
from unittest.mock import MagicMock, Mock, patch

import pytest

from services.parser import DocumentParser, get_file_type


class TestDocumentParser:
    """Test suite for DocumentParser class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.parser = DocumentParser()

    def test_parse_txt_file(self):
        """Test parsing plain text files."""
        content = b"Hello, this is a text file.\nWith multiple lines."
        result = self.parser.parse(content, "txt")
        assert result == "Hello, this is a text file.\nWith multiple lines."

    def test_parse_md_file(self):
        """Test parsing markdown files."""
        content = b"# Markdown Title\n\nSome **bold** text."
        result = self.parser.parse(content, "md")
        assert result == "# Markdown Title\n\nSome **bold** text."

    def test_parse_txt_with_encoding_errors(self):
        """Test parsing text files with encoding errors (should ignore)."""
        content = b"Valid text \xff\xfe invalid bytes"
        result = self.parser.parse(content, "txt")
        assert "Valid text" in result

    def test_parse_unsupported_type_raises_error(self):
        """Test that unsupported file types raise ValueError."""
        content = b"some content"
        with pytest.raises(ValueError) as exc_info:
            self.parser.parse(content, "xlsx")

        assert "Unsupported file type: xlsx" in str(exc_info.value)
        assert "docx, md, pdf, pptx, txt" in str(exc_info.value)

    def test_parse_with_dot_prefix(self):
        """Test parsing with dot prefix in file type (.pdf, .docx, etc)."""
        content = b"Simple text content"
        result = self.parser.parse(content, ".txt")
        assert result == "Simple text content"

    def test_parse_with_uppercase_type(self):
        """Test parsing with uppercase file type (PDF, DOCX, etc)."""
        content = b"Uppercase test"
        result = self.parser.parse(content, "TXT")
        assert result == "Uppercase test"

    def test_parse_with_dot_and_uppercase(self):
        """Test parsing with both dot prefix and uppercase (.PDF)."""
        content = b"Mixed case test"
        result = self.parser.parse(content, ".MD")
        assert result == "Mixed case test"

    @patch('services.parser.PdfReader')
    def test_parse_pdf_single_page(self, mock_pdf_reader):
        """Test parsing single-page PDF."""
        # Setup mock
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page content here"

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_pdf_reader.return_value = mock_reader

        # Test
        content = b"fake pdf bytes"
        result = self.parser.parse(content, "pdf")

        # Verify
        assert result == "[Page 1]\nPage content here"
        mock_pdf_reader.assert_called_once()
        call_args = mock_pdf_reader.call_args[0]
        assert isinstance(call_args[0], io.BytesIO)

    @patch('services.parser.PdfReader')
    def test_parse_pdf_multiple_pages(self, mock_pdf_reader):
        """Test parsing multi-page PDF."""
        # Setup mock pages
        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "First page text"

        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "Second page text"

        mock_page3 = MagicMock()
        mock_page3.extract_text.return_value = "Third page text"

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page1, mock_page2, mock_page3]
        mock_pdf_reader.return_value = mock_reader

        # Test
        content = b"fake pdf bytes"
        result = self.parser.parse(content, "pdf")

        # Verify
        expected = "[Page 1]\nFirst page text\n\n[Page 2]\nSecond page text\n\n[Page 3]\nThird page text"
        assert result == expected

    @patch('services.parser.PdfReader')
    def test_parse_pdf_with_empty_pages(self, mock_pdf_reader):
        """Test parsing PDF with empty pages (should be skipped)."""
        # Setup mock pages - some empty
        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "First page text"

        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = ""  # Empty

        mock_page3 = MagicMock()
        mock_page3.extract_text.return_value = "   "  # Whitespace only

        mock_page4 = MagicMock()
        mock_page4.extract_text.return_value = "Fourth page text"

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page1, mock_page2, mock_page3, mock_page4]
        mock_pdf_reader.return_value = mock_reader

        # Test
        content = b"fake pdf bytes"
        result = self.parser.parse(content, "pdf")

        # Verify - empty pages should be skipped
        expected = "[Page 1]\nFirst page text\n\n[Page 4]\nFourth page text"
        assert result == expected

    @patch('services.parser.DocxDocument')
    def test_parse_docx_paragraphs_only(self, mock_docx_document):
        """Test parsing DOCX with only paragraphs."""
        # Setup mock paragraphs
        mock_para1 = MagicMock()
        mock_para1.text = "First paragraph"
        mock_para1.style.name = "Normal"

        mock_para2 = MagicMock()
        mock_para2.text = "Second paragraph"
        mock_para2.style.name = "Normal"

        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para1, mock_para2]
        mock_doc.tables = []
        mock_docx_document.return_value = mock_doc

        # Test
        content = b"fake docx bytes"
        result = self.parser.parse(content, "docx")

        # Verify
        expected = "First paragraph\nSecond paragraph"
        assert result == expected

    @patch('services.parser.DocxDocument')
    def test_parse_docx_with_headings(self, mock_docx_document):
        """Test parsing DOCX with headings."""
        # Setup mock paragraphs with headings
        mock_heading = MagicMock()
        mock_heading.text = "Introduction"
        mock_heading.style.name = "Heading 1"

        mock_para = MagicMock()
        mock_para.text = "This is content under the heading."
        mock_para.style.name = "Normal"

        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_heading, mock_para]
        mock_doc.tables = []
        mock_docx_document.return_value = mock_doc

        # Test
        content = b"fake docx bytes"
        result = self.parser.parse(content, "docx")

        # Verify
        assert "\n## Introduction\n" in result
        assert "This is content under the heading." in result

    @patch('services.parser.DocxDocument')
    def test_parse_docx_with_tables(self, mock_docx_document):
        """Test parsing DOCX with tables."""
        # Setup mock table
        mock_cell1 = MagicMock()
        mock_cell1.text = "Header 1"
        mock_cell2 = MagicMock()
        mock_cell2.text = "Header 2"

        mock_cell3 = MagicMock()
        mock_cell3.text = "Value 1"
        mock_cell4 = MagicMock()
        mock_cell4.text = "Value 2"

        mock_row1 = MagicMock()
        mock_row1.cells = [mock_cell1, mock_cell2]

        mock_row2 = MagicMock()
        mock_row2.cells = [mock_cell3, mock_cell4]

        mock_table = MagicMock()
        mock_table.rows = [mock_row1, mock_row2]

        mock_doc = MagicMock()
        mock_doc.paragraphs = []
        mock_doc.tables = [mock_table]
        mock_docx_document.return_value = mock_doc

        # Test
        content = b"fake docx bytes"
        result = self.parser.parse(content, "docx")

        # Verify
        assert "Header 1 | Header 2" in result
        assert "Value 1 | Value 2" in result

    @patch('services.parser.DocxDocument')
    def test_parse_docx_skip_empty_paragraphs(self, mock_docx_document):
        """Test parsing DOCX skips empty paragraphs."""
        # Setup mock paragraphs - some empty
        mock_para1 = MagicMock()
        mock_para1.text = "First paragraph"
        mock_para1.style.name = "Normal"

        mock_para2 = MagicMock()
        mock_para2.text = "   "  # Whitespace only
        mock_para2.style.name = "Normal"

        mock_para3 = MagicMock()
        mock_para3.text = "Third paragraph"
        mock_para3.style.name = "Normal"

        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para1, mock_para2, mock_para3]
        mock_doc.tables = []
        mock_docx_document.return_value = mock_doc

        # Test
        content = b"fake docx bytes"
        result = self.parser.parse(content, "docx")

        # Verify - empty paragraphs should be skipped
        assert result == "First paragraph\nThird paragraph"

    @patch('services.parser.Presentation')
    def test_parse_pptx_single_slide(self, mock_presentation):
        """Test parsing single-slide PowerPoint."""
        # Setup mock shape with text
        mock_shape = MagicMock()
        mock_shape.text = "Slide title and content"
        mock_shape.has_table = False

        mock_slide = MagicMock()
        mock_slide.shapes = [mock_shape]

        mock_prs = MagicMock()
        mock_prs.slides = [mock_slide]
        mock_presentation.return_value = mock_prs

        # Test
        content = b"fake pptx bytes"
        result = self.parser.parse(content, "pptx")

        # Verify
        expected = "[Slide 1]\nSlide title and content"
        assert result == expected

    @patch('services.parser.Presentation')
    def test_parse_pptx_multiple_slides(self, mock_presentation):
        """Test parsing multi-slide PowerPoint."""
        # Setup mock slides
        mock_shape1 = MagicMock()
        mock_shape1.text = "First slide content"
        mock_shape1.has_table = False

        mock_slide1 = MagicMock()
        mock_slide1.shapes = [mock_shape1]

        mock_shape2 = MagicMock()
        mock_shape2.text = "Second slide content"
        mock_shape2.has_table = False

        mock_slide2 = MagicMock()
        mock_slide2.shapes = [mock_shape2]

        mock_prs = MagicMock()
        mock_prs.slides = [mock_slide1, mock_slide2]
        mock_presentation.return_value = mock_prs

        # Test
        content = b"fake pptx bytes"
        result = self.parser.parse(content, "pptx")

        # Verify
        expected = "[Slide 1]\nFirst slide content\n\n[Slide 2]\nSecond slide content"
        assert result == expected

    @patch('services.parser.Presentation')
    def test_parse_pptx_with_tables(self, mock_presentation):
        """Test parsing PowerPoint with tables."""
        # Setup mock table
        mock_cell1 = MagicMock()
        mock_cell1.text = "Column A"
        mock_cell2 = MagicMock()
        mock_cell2.text = "Column B"

        mock_row = MagicMock()
        mock_row.cells = [mock_cell1, mock_cell2]

        mock_table = MagicMock()
        mock_table.rows = [mock_row]

        mock_shape = MagicMock()
        mock_shape.text = ""
        mock_shape.has_table = True
        mock_shape.table = mock_table

        mock_slide = MagicMock()
        mock_slide.shapes = [mock_shape]

        mock_prs = MagicMock()
        mock_prs.slides = [mock_slide]
        mock_presentation.return_value = mock_prs

        # Test
        content = b"fake pptx bytes"
        result = self.parser.parse(content, "pptx")

        # Verify
        assert "[Slide 1]" in result
        assert "Column A | Column B" in result

    @patch('services.parser.Presentation')
    def test_parse_pptx_skip_empty_shapes(self, mock_presentation):
        """Test parsing PowerPoint skips empty shapes."""
        # Setup mock shapes - some empty
        mock_shape1 = MagicMock()
        mock_shape1.text = "Content"
        mock_shape1.has_table = False

        mock_shape2 = MagicMock()
        mock_shape2.text = "   "  # Whitespace only
        mock_shape2.has_table = False

        mock_slide = MagicMock()
        mock_slide.shapes = [mock_shape1, mock_shape2]

        mock_prs = MagicMock()
        mock_prs.slides = [mock_slide]
        mock_presentation.return_value = mock_prs

        # Test
        content = b"fake pptx bytes"
        result = self.parser.parse(content, "pptx")

        # Verify
        lines = result.split('\n')
        assert len(lines) == 2  # Only slide number and content shape
        assert "[Slide 1]" in result
        assert "Content" in result

    @patch('services.parser.Presentation')
    def test_parse_pptx_skip_empty_slides(self, mock_presentation):
        """Test parsing PowerPoint skips slides with no content."""
        # Setup mock slides - one empty
        mock_shape1 = MagicMock()
        mock_shape1.text = "Content on slide 1"
        mock_shape1.has_table = False

        mock_slide1 = MagicMock()
        mock_slide1.shapes = [mock_shape1]

        # Empty slide
        mock_empty_shape = MagicMock()
        mock_empty_shape.text = ""
        mock_empty_shape.has_table = False

        mock_slide2 = MagicMock()
        mock_slide2.shapes = [mock_empty_shape]

        mock_prs = MagicMock()
        mock_prs.slides = [mock_slide1, mock_slide2]
        mock_presentation.return_value = mock_prs

        # Test
        content = b"fake pptx bytes"
        result = self.parser.parse(content, "pptx")

        # Verify - only slide 1 should appear
        assert "[Slide 1]" in result
        assert "[Slide 2]" not in result
        assert "Content on slide 1" in result


class TestGetFileType:
    """Test suite for get_file_type function."""

    def test_get_file_type_pdf(self):
        """Test extracting PDF file type."""
        assert get_file_type("document.pdf") == "pdf"

    def test_get_file_type_docx(self):
        """Test extracting DOCX file type."""
        assert get_file_type("report.docx") == "docx"

    def test_get_file_type_pptx(self):
        """Test extracting PPTX file type."""
        assert get_file_type("presentation.pptx") == "pptx"

    def test_get_file_type_txt(self):
        """Test extracting TXT file type."""
        assert get_file_type("notes.txt") == "txt"

    def test_get_file_type_md(self):
        """Test extracting MD file type."""
        assert get_file_type("README.md") == "md"

    def test_get_file_type_uppercase(self):
        """Test extracting file type with uppercase extension."""
        assert get_file_type("DOCUMENT.PDF") == "pdf"

    def test_get_file_type_mixed_case(self):
        """Test extracting file type with mixed case extension."""
        assert get_file_type("file.Docx") == "docx"

    def test_get_file_type_with_path(self):
        """Test extracting file type from full path."""
        assert get_file_type("/path/to/document.pdf") == "pdf"

    def test_get_file_type_with_multiple_dots(self):
        """Test extracting file type from filename with multiple dots."""
        assert get_file_type("my.backup.file.docx") == "docx"

    def test_get_file_type_no_extension(self):
        """Test extracting file type from filename without extension."""
        assert get_file_type("README") == ""

    def test_get_file_type_hidden_file(self):
        """Test extracting file type from hidden file."""
        assert get_file_type(".gitignore") == ""
