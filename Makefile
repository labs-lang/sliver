.PHONY: osx linux rmsentinels
osx: platform = osx.10.12-x64
osx: VENDOR_DIR = vendor/osx
linux: VENDOR_DIR = vendor/linux
osx_cseq: platform = osx.10.12-x64
linux: platform = linux-x64
linux_cseq: platform = linux-x64
zip_linux: platform = linux-x64

# Source files
sliver_sources = $(wildcard sliver/**/*.py) 
labs_sources = $(wildcard labs/**/*.fs) 
labs_templates = $(wildcard labs/LabsTranslate/templates/**/*.c) $(wildcard labs/LabsTranslate/templates/**/*.lnt) 
labs_examples = $(wildcard labs_examples/**/*.*) labs-examples/LICENSE

VERSION := $(strip $(shell grep version sliver/app/__about__.py | grep = | sed 's/"//g' | awk 'NF{print $$NF}'))
RELEASENAME = sliver-v$(VERSION)_$(strip $(subst -,_, ${platform}))
BUILD_DIR = build/$(platform)
SLIVER_DIR = $(BUILD_DIR)/sliver
BLACKLIST = $(shell git ls-files --others --exclude-standard)

build/%/sliver/labs/LabsTranslate : $(labs_sources) $(labs_templates)
	@echo Building LabsTranslate...
	dotnet publish labs/LabsTranslate/LabsTranslate.fsproj -r $(platform) -c Release --self-contained -o $(SLIVER_DIR)/labs -p:PublishSingleFile=true -p:PublishTrimmed=true ;
	@rm -f $(SLIVER_DIR)/labs/*.pdb ;

# sliver.py is a sentinel for files that should go in the root dir
build/%/sliver.py :
	@cp ./HISTORY $(@D) ;
	@cp ./LICENSE $(@D) ;
	@cp ./*.* $(@D) ;
	@# Remove untracked files from release directory
	@rm -f $(foreach f, $(BLACKLIST), $(@D)/$(f)) ;

build/%/examples/README.md : $(labs_examples)
	@echo Copying examples...
	@cp -r labs-examples $(BUILD_DIR)/examples

build/%/sliver/__main__.py : $(sliver_sources)
	@echo Copying SLiVER...
	@cp -r sliver $(BUILD_DIR) ;

build/%/minisat:
	@echo Copying PlanckSAT...
	@cp -r $(VENDOR_DIR)/minisat/minisat $(SLIVER_DIR)/minisat/minisat
	@cp -r $(VENDOR_DIR)/minisat/LICENSE $(SLIVER_DIR)/minisat/LICENSE

build/%/cbmc-simulator:
	@echo Copying CBMC...
	cp -r $(VENDOR_DIR)/cbmc/* $(SLIVER_DIR)/cbmc/

# Clean up sentinels for stuff that must be copied every time
# TODO: gradually get rid of this and trust Make's judgment
rmsentinels:
	@mkdir -p $(BUILD_DIR) ;
	@rm -f $(BUILD_DIR)/sliver.py ;
	@rm -f $(SLIVER_DIR)/__main__.py ;
	@rm -f $(SLIVER_DIR)/minisat/minisat ;
	@rm -f $(SLIVER_DIR)/cbmc/cbmc-simulator ;

osx: rmsentinels \
	build/osx.10.12-x64/sliver/__main__.py \
	build/osx.10.12-x64/sliver.py \
	build/osx.10.12-x64/sliver/labs/LabsTranslate \
	build/osx.10.12-x64/sliver/minisat/minisat \
	build/osx.10.12-x64/examples/README.md

linux: rmsentinels \
	build/linux-x64/sliver/__main__.py \
	build/linux-x64/sliver.py \
	build/linux-x64/sliver/labs/LabsTranslate \
	build/linux-x64/sliver/minisat/minisat \
	build/linux-x64/examples/README.md \
	build/linux-x64/sliver/cbmc/cbmc-simulator

zip_linux : linux
	@rm -rf build/$(RELEASENAME);
	@rm -f build/$(RELEASENAME).zip;
	cp -r build/$(platform) build/$(RELEASENAME)
	cd build && zip -r $(RELEASENAME).zip $(RELEASENAME)
	rm -rf build/$(RELEASENAME)
