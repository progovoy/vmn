NAME=vmn

.PHONY: build upload_to_pypi dist check docs major _major minor _minor patch _patch rc _rc _publish

build: check

_publish: clean
	@echo "Publishing"
	vmn show ${EXTRA_SHOW_ARGS} --verbose vmn > .vmn/vmn/ver.yml
	python3 ${PWD}/gen_ver.py
	python3 setup.py sdist bdist_wheel

upload_to_pypi:
	twine upload ${PWD}/dist/*

major: check _major _publish

_major:
	@echo "Major Release"
	vmn stamp -r major ${NAME}

minor: check _minor _publish

_minor:
	@echo "Minor Release"
	vmn stamp -r minor ${NAME}

patch: check _patch _publish

_patch:
	@echo "Patch Release"
	vmn stamp -r patch ${NAME}

rc: check _rc _publish

_rc:
	@echo "RC Release"
	vmn stamp ${NAME}
	$(eval EXTRA_SHOW_ARGS := --template [{major}][.{minor}][.{patch}][{prerelease}])

check:
	@echo "-------------------------------------------------------------"
	@echo "-------------------------------------------------------------"
	@echo "-~      Running static checks                              --"
	@echo "-------------------------------------------------------------"
	black ${PWD}
	@echo "-~      Running unit tests                                 --"
	${PWD}/tests/run_tests.sh
	@echo "-------------------------------------------------------------"
	@echo "-------------------------------------------------------------"
	@echo "-------------------------------------------------------------"

clean:
	git checkout -- ${PWD}/version_stamp/version.py
	rm -rf ${PWD}/dist
	rm -rf ${PWD}/build
