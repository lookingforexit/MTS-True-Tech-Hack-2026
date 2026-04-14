SERVICE_DIRS := $(patsubst %/Makefile,%,$(wildcard services/*/Makefile))

.PHONY: all generate $(SERVICE_DIRS)

all: generate

generate: $(SERVICE_DIRS)

$(SERVICE_DIRS):
	$(MAKE) -C $@
