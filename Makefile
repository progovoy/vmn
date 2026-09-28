# NAME=vmn releases the vmn distribution; NAME=vmn_exp releases vmn-exp and
# vmn-exp-sdk together (one version). `vmn stamp` writes the new version into
# the packages' pyproject.toml files (version_backends in .vmn/<NAME>/conf.yml).
NAME=vmn

ifeq (${NAME},vmn_exp)
PACKAGES=packages/vmn-exp-sdk packages/vmn-exp
else
PACKAGES=packages/vmn
endif

.PHONY: build upload dist check docs major _major minor _minor patch _patch rc _rc _build _build_ui _run_black

build: check _build

_build_ui:
	@echo "Building web UI"
	npm install --prefix ${PWD}/packages/vmn-exp/webui
	npm run build --prefix ${PWD}/packages/vmn-exp/webui

_build: clean $(if $(filter vmn_exp,${NAME}),_build_ui)
	@echo "Building ${PACKAGES}"
	for pkg in ${PACKAGES}; do uv build --out-dir ${PWD}/dist $${pkg} || exit 1; done

upload:
	twine upload --verbose ${PWD}/dist/*

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
	@echo "-------------------------------------------------------------"
	@echo "-------------------------------------------------------------"
	@echo "-------------------------------------------------------------"

clean:
	rm -rf ${PWD}/dist
	rm -rf ${PWD}/build

package: _package
_package: 
	@echo "Container Packaging"
	@docker build -t vmn/vmn:latest -f Dockerfile .
