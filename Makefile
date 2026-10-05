# NAME=vmn releases the vmn distribution; NAME=vmn_exp releases vmn-exp and
# vmn-exp-sdk together (one version). `vmn stamp` writes the new version into
# the packages' pyproject.toml files (version_backends in .vmn/<NAME>/conf.yml).
NAME=vmn
DIST=${PWD}/dist
TWINE=twine

.PHONY: build upload dist check docs major _major minor _minor patch _patch rc _rc _build _build_ui _run_black

build: check _build

_build_ui:
	@echo "Building web UI"
	npm install --prefix ${PWD}/packages/vmn-exp/webui
	npm run build --prefix ${PWD}/packages/vmn-exp/webui

# Builds at the version `vmn show ${NAME}` reports (the release after a
# `vmn release`, not the rc the stamp wrote into the files); see build_dist.sh.
_build: clean $(if $(filter vmn_exp,${NAME}),_build_ui)
	${PWD}/build_dist.sh ${NAME} ${DIST}

# Each file goes to its project's ~/.pypirc section (per-project tokens), or to
# [pypi] when that section is missing (one account-wide token).
upload:
	@for f in ${DIST}/*; do \
		case $$(basename $$f) in \
			vmn_exp_sdk-*) section=vmn-exp-sdk ;; \
			vmn_exp-*) section=vmn-exp ;; \
			*) section=pypi ;; \
		esac; \
		grep -q "^\[$$section\]" ~/.pypirc 2>/dev/null || section=pypi; \
		${TWINE} upload --verbose --skip-existing -r $$section $$f || exit 1; \
	done

major: check _major _build

_major:
	@echo "Major Release"
	vmn stamp -r major ${NAME}

minor: check _minor _build

_minor:
	@echo "Minor Release"
	vmn stamp -r minor ${NAME}

patch: check _patch _build

_patch:
	@echo "Patch Release"
	vmn stamp -r patch ${NAME}

rc: check _rc _build

_rc:
	@echo "RC Release"
	vmn stamp ${NAME}

_run_black:
	@echo "-~      Run Black                              --"
	black --version
	black --diff ${PWD}
	black ${PWD}

check: _run_black
	@echo "-------------------------------------------------------------"
	@echo "-------------------------------------------------------------"
	@echo "-~      Running static checks                              --"
	@echo "-------------------------------------------------------------"
	@echo "-~      Running unit tests                                 --"
	${PWD}/tests/run_tests.sh
	${PWD}/tests/run_tests.sh --suite exp
	@echo "-------------------------------------------------------------"
	@echo "-------------------------------------------------------------"
	@echo "-------------------------------------------------------------"

clean:
	rm -rf ${DIST}
	rm -rf ${PWD}/build

package: _package
_package: 
	@echo "Container Packaging"
	@docker build -t vmn/vmn:latest -f Dockerfile .
