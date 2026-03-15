# CHANGELOG


## [2.1.1](https://github.com/IAmTheMitchell/renogy-ble/compare/v2.1.0...v2.1.1) (2026-03-15)


### Bug Fixes

* harden smart shunt live packet parsing ([#61](https://github.com/IAmTheMitchell/renogy-ble/issues/61)) ([2eb1d2a](https://github.com/IAmTheMitchell/renogy-ble/commit/2eb1d2aee7d139a5b35465ea2e9f6746c266a0f6))

## [2.1.0](https://github.com/IAmTheMitchell/renogy-ble/compare/v2.0.0...v2.1.0) (2026-03-15)


### Features

* add Renogy inverter BLE/protocol support ([0bc6799](https://github.com/IAmTheMitchell/renogy-ble/commit/0bc679973b019893b54be9753f7d1729290754a2))

## [2.0.0](https://github.com/IAmTheMitchell/renogy-ble/compare/v1.3.1...v2.0.0) (2026-03-12)


### ⚠ BREAKING CHANGES

* require Python 3.14 ([#55](https://github.com/IAmTheMitchell/renogy-ble/issues/55))

### Features

* require Python 3.14 ([#55](https://github.com/IAmTheMitchell/renogy-ble/issues/55)) ([245b006](https://github.com/IAmTheMitchell/renogy-ble/commit/245b0066a0a045e242d7021f8479ff16e95c9ee3))


### Bug Fixes

* relax the bleak-retry-connector version requirement to be compatible with Home Assistant 2026.3.0 ([#56](https://github.com/IAmTheMitchell/renogy-ble/issues/56)) ([e8b9297](https://github.com/IAmTheMitchell/renogy-ble/commit/e8b9297c28b699a10c7c6b5d3b99fc776f9b85eb))
* rerun prerelease on release please updates ([#53](https://github.com/IAmTheMitchell/renogy-ble/issues/53)) ([3892614](https://github.com/IAmTheMitchell/renogy-ble/commit/38926149753eb05d87c5b6dee26d0c942713925f))

## [1.3.1](https://github.com/IAmTheMitchell/renogy-ble/compare/v1.3.0...v1.3.1) (2026-03-11)


### Bug Fixes

* split shunt energy into charged and discharged totals ([#51](https://github.com/IAmTheMitchell/renogy-ble/issues/51)) ([448d2ff](https://github.com/IAmTheMitchell/renogy-ble/commit/448d2ffe7474931b4a16e586a8efb88aea3d1a88))

## [1.3.0](https://github.com/IAmTheMitchell/renogy-ble/compare/v1.2.1...v1.3.0) (2026-03-10)


### Features

* add Smart Shunt payload parsing functionality ([#38](https://github.com/IAmTheMitchell/renogy-ble/issues/38)) ([5d8aaf4](https://github.com/IAmTheMitchell/renogy-ble/commit/5d8aaf43f53f3939a2e6ae51338b3d0a8ed09713))


### Documentation

* add contributing guidelines for the project ([829b08d](https://github.com/IAmTheMitchell/renogy-ble/commit/829b08db221cf6a6b97a10168af106025a993bb4))
* add contributing guidelines for the project ([647399d](https://github.com/IAmTheMitchell/renogy-ble/commit/647399de628d5b2f6e8b3a58775779e829b60d84))
* move CONTRIBUTING.md ([c7ea98c](https://github.com/IAmTheMitchell/renogy-ble/commit/c7ea98c9dc72754f1da74ea95ebb9cef83fb0dd4))

## [1.2.1](https://github.com/IAmTheMitchell/renogy-ble/compare/v1.2.0...v1.2.1) (2026-02-10)


### Bug Fixes

* ensure proper client disconnection in RenogyBleClient methods ([#33](https://github.com/IAmTheMitchell/renogy-ble/issues/33)) ([4513b56](https://github.com/IAmTheMitchell/renogy-ble/commit/4513b56070abf8b920a17b7f827a451ab5b61a8d))

## [1.2.0](https://github.com/IAmTheMitchell/renogy-ble/compare/v1.1.0...v1.2.0) (2026-01-24)


### Features

* turn controller load on/off ([#20](https://github.com/IAmTheMitchell/renogy-ble/issues/20)) ([7ce7666](https://github.com/IAmTheMitchell/renogy-ble/commit/7ce76663de58c077952ac71392284068f4b81fa9))

## [1.1.0](https://github.com/IAmTheMitchell/renogy-ble/compare/v1.0.2...v1.1.0) (2026-01-15)


### Features

* add DC-DC charger (DCC) support ([#24](https://github.com/IAmTheMitchell/renogy-ble/issues/24)) ([5155299](https://github.com/IAmTheMitchell/renogy-ble/commit/51552997b2f359bd2218775864b744c4f1e7c1ed))

## [1.0.2](https://github.com/IAmTheMitchell/renogy-ble/compare/v1.0.1...v1.0.2) (2026-01-08)


### Bug Fixes

* handle negative temps in parser ([#16](https://github.com/IAmTheMitchell/renogy-ble/issues/16)) ([8be77e3](https://github.com/IAmTheMitchell/renogy-ble/commit/8be77e3cdf871142009aa30950ab3c97864ba350))

## [1.0.1](https://github.com/IAmTheMitchell/renogy-ble/compare/v1.0.0...v1.0.1) (2026-01-08)


### Bug Fixes

* support bleak 2.0.0+ ([#17](https://github.com/IAmTheMitchell/renogy-ble/issues/17)) ([a6c8df3](https://github.com/IAmTheMitchell/renogy-ble/commit/a6c8df396b76dd12d6e96b8dee15bc2dab075910))

## [1.0.0](https://github.com/IAmTheMitchell/renogy-ble/compare/v0.2.2...v1.0.0) (2026-01-01)


### ⚠ BREAKING CHANGES

* migrate Bluetooth logic to library ([#12](https://github.com/IAmTheMitchell/renogy-ble/issues/12))

### Features

* migrate Bluetooth logic to library ([#12](https://github.com/IAmTheMitchell/renogy-ble/issues/12)) ([e9f1681](https://github.com/IAmTheMitchell/renogy-ble/commit/e9f1681e066853f4a74e2c2ea4584da8bf88f4da))


### Miscellaneous Chores

* release 1.0.0 ([2cf808b](https://github.com/IAmTheMitchell/renogy-ble/commit/2cf808b659874e3f5e266c474780fe4a409ee267))

## [0.2.2](https://github.com/IAmTheMitchell/renogy-ble/compare/v0.2.1...v0.2.2) (2025-12-13)


### Bug Fixes

* support signed integers for temperatures ([03cb4cf](https://github.com/IAmTheMitchell/renogy-ble/commit/03cb4cfc4204fee76f9c5930c6285f4bc08b155b))


### Documentation

* add AGENTS.md ([1994ef9](https://github.com/IAmTheMitchell/renogy-ble/commit/1994ef9b1185d41165db6d623d5f7a56de428ba0))
* update readme ci labels ([d25675a](https://github.com/IAmTheMitchell/renogy-ble/commit/d25675a6ab2f4791c10c2ff30223b0de9706bdda))

## v0.2.1 (2025-04-02)

### Bug Fixes

- Configure semantic release
  ([`0accb9a`](https://github.com/IAmTheMitchell/renogy-ble/commit/0accb9a87e6444dc05e2db0dfecde807a3619b10))


## v0.2.0 (2025-04-02)

### Chores

- Add CI for python tests
  ([`697f479`](https://github.com/IAmTheMitchell/renogy-ble/commit/697f479048a3db83243fbcd2f9eab670c1b4c96a))

- Add ci to automate releases
  ([`2569b7c`](https://github.com/IAmTheMitchell/renogy-ble/commit/2569b7c4cf91043eb384091cb2159b732bb09f00))

- Test python 3.13
  ([`700484d`](https://github.com/IAmTheMitchell/renogy-ble/commit/700484d0f1e23bc114c11b417dae172ee7198b6f))

### Features

- Support charge controllers
  ([`17d31c6`](https://github.com/IAmTheMitchell/renogy-ble/commit/17d31c6869d2dbe35e4517cd2c84e72f319c05b4))


## v0.1.3 (2025-03-19)


## v0.1.2 (2025-03-19)
