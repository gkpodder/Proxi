# Makefile
# From https://danielkaes.wordpress.com/2009/03/14/compiling-latex-documents-using-makefiles/

PROJECT=POC_Team_Contrib
TEX=pdflatex
PROJECT2=Rev0_Team_Contrib
PROJECT3=Final_Team_Contrib
BIBTEX=bibtex
BUILDTEX=$(TEX) $(PROJECT).tex
BUILDTEX2=$(TEX) $(PROJECT2).tex
BUILDTEX3=$(TEX) $(PROJECT3).tex

all:
	$(BUILDTEX)
	$(BUILDTEX2)
	$(BUILDTEX3)
#	$(BIBTEX) $(PROJECT)
#	$(BUILDTEX)
	$(BUILDTEX)

clean-all:
	rm -f *.dvi *.log *.bak *.aux *.bbl *.blg *.idx *.ps *.eps *.pdf *.toc *.out *~

clean:
	rm -f *.log *.bak *.aux *.bbl *.blg *.idx *.toc *.out *~