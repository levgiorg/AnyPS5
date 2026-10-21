# libSceSysCore technical debt

### Unknown function info

- [libSceSysCore pending exports](../../../core/libs/prx/libSceSysCore/Export.cpp) (libSceSysCore) - 6 named callable exports are present in the public PS5 payload SDK's [stub table](https://github.com/ps5-payload-dev/sdk/blob/a7685ce8e97ce1f8a4f38253a41d54241c9124f1/sce_stubs/libSceSysCore.c), which marks each of them a function. Their signatures and behavior are unverified; each declaration uses the no-parameter unknown-signature convention and throws through `NotImplemented_nid_no_patch`.
- [sceApplicationGetAppInfoByAppId](../../../core/libs/prx/libSceSysCore/Export.cpp) takes a 32-bit application ID and a writable 152-byte record. The service fills the record through IPC; its complete field layout remains unresolved. The SystemService caller consumes a subrecord beginning at byte 48.
