SHELL = /bin/sh

override SITES = \
	ajax.googleapis.com \
	cdnjs.cloudflare.com \
	github.com \
	gist.github.com \
	github.githubassets.com \
	zenodo.org

.PHONY : all
all : \
	build/nginx/mime.types \
	build/nginx/nginx.conf \
	build/nginx/snippets/ssl.conf \
	build/nginx/snippets/static_file_proxy.conf \
	$(foreach \
		SITE, \
		$(SITES), \
		build/nginx/conf.d/$(SITE).conf \
		build/nginx/ssl/$(SITE).crt \
		build/nginx/ssl/$(SITE).key \
	)

.PHONY : clean
clean :
	rm -r build

build/nginx/mime.types : build/tmp/data.json
	mkdir -p build/nginx
	minijinja-cli src/mime.types.jinja $< -o $@

build/nginx/nginx.conf : build/tmp/data.json
	mkdir -p build/nginx
	minijinja-cli src/nginx.conf.jinja $< -o $@

build/nginx/conf.d/%.conf : build/tmp/data.json
	mkdir -p build/nginx/conf.d
	if [ -f src/conf.d/$*.conf.jinja ]; then \
		minijinja-cli src/conf.d/$*.conf.jinja $< -o $@; \
	else \
		cp src/conf.d/$*.conf $@; \
	fi

build/nginx/snippets/%.conf : build/tmp/data.json
	mkdir -p build/nginx/snippets
	if [ -f src/snippets/$*.conf.jinja ]; then \
		minijinja-cli src/snippets/$*.conf.jinja $< -o $@; \
	else \
		cp src/snippets/$*.conf $@; \
	fi

build/nginx/ssl/%.crt : build/tmp/%.csr
ifndef CA
	$(error You need to provide a CA file)
endif
ifndef CAkey
	$(error You need to provide a CAkey file)
endif
	openssl x509 \
		-in $< \
		-req \
		-copy_extensions copy \
		-out $@ \
		-days 999 \
		-sha256 \
		-CA $(CA) \
		-CAkey $(CAkey)

build/nginx/ssl/%.key :
	mkdir -p build/nginx/ssl
	openssl genrsa -out $@ 2048

build/tmp/%.csr : build/nginx/ssl/%.key
	mkdir -p build/tmp
	MSYS2_ARG_CONV_EXCL='*' \
		openssl req \
		-out $@ \
		-new \
		-key $< \
		-config '' \
		-addext subjectAltName=DNS:$* \
		-subj /CN=$*/O=nginx-conf

build/tmp/data.json : build/tmp/ext_mime.db build/tmp/meta.json
	python3 -I scripts/make_data.py

build/tmp/ext_mime.db :
	mkdir -p build/tmp
	curl -Lo $@ https://cdn.jsdelivr.net/gh/mime-types/mime-types-data@main/data/ext_mime.db

build/tmp/meta.json :
	mkdir -p build/tmp
	curl -Lo $@ https://api.github.com/meta

.SECONDARY : build/tmp/ext_mime.db build/tmp/meta.json
