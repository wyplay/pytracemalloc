PYTHON=python

all:
	$(PYTHON) setup.py build

install: all
	$(PYTHON) setup.py install

clean:
	rm -rf build dist *.pyc __pycache__

