# Version MaNaging package - VMN &nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ![plusonelogo3](https://user-images.githubusercontent.com/5350434/85959337-8677e180-b9a4-11ea-817a-79dbf057de30.png)

A simple package for auto increasing version numbers of any application agnostic to language or architecture.


`vmn` is fully compliant with https://semver.org semantics

## Usage

```sh
cd to/your/repository
vmn -h

vmn init
vmn stamp -r patch <app-name>
vmn stamp -r minor <app-name> --starting-version 1.0.6.8
vmn stamp -r major <app-name>
vmn show <app-name>
vmn goto -v 1.0.1.0 <app-name>
```

### Concurrent builds

`vmn`  supports simultaneous builds. You can safely run multiple instances of `vmn`



## Installation

```sh
pip3 install vmn
```

## Why `vmn` is agnostic to application language?
It is the application's reposibility to actualy set the version number that is in the `ver.yml` file to the application's code during its build phase. 


## Contributing

If you want to contribute to version-stamp development:

1. Make a fresh fork of the repository

2. Test your work

4. Pull Request

This project is just a small side project that I've started, decided to share it. We'll see if it will ramp up.

We will thank you for every contribution :)
