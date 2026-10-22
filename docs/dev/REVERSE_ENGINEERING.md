# Reading titles and libraries

Many exports have no source that gives their signature or behaviour. Two places still hold them: the code of a title
that calls the export (its call sites) and the code of the library itself. This page covers how to read both, what each
one settles, and how to cite it.

## Sources, strongest first

1. **A console measurement**: a homebrew payload that calls the function and records what it returns, with the
   firmware version (for example `sceVoiceQoSEnd`, #1407).
2. **The library's own code**: a firmware module, or a copy of an SDK module that a title ships in `sce_module/`. It gives
   behaviour, error codes, layouts and validation order ([libSceJobManager](debt/libSceJobManager.md),
   [libSceRtc](debt/libSceRtc.md), [libSceHttp](debt/libSceHttp.md)). A module a title ships is not reimplemented
   ([CONTRIBUTING](../../CONTRIBUTING.md)); it can still be read to learn how a system library behaves.
3. **Other implementations and SDK bindings**: KytyPS5, shadPS4, fpPS4, SharpProspero, Orbital. PS4 sources may differ
   from the PS5 ABI.
4. **A title's call sites**: the arguments, their widths, buffer sizes, which pointers are outputs and which results the
   title checks. They show what the caller expects, not what the library does.

When sources disagree, say so in the pull request and in the debt entry.

## What settles an export's name, and what settles its kind

A NID is a hash of the name, so a NID in a database is not evidence: only a name is. The
sources differ in what they settle.

| Source | Settles |
| --- | --- |
| The [NID name database](https://github.com/zecoxao/sce_symbols) (`aerolib.csv` at `2883963a0a514ba6e77407a08ef4730a65e88254`) | The name, and the NID that follows from it |
| The public PS5 payload SDK's [stub tables](https://github.com/ps5-payload-dev/sdk/blob/a7685ce8e97ce1f8a4f38253a41d54241c9124f1/sce_stubs/libSceLibcInternal.c) | The name and the kind: `.type <name>, @function` or `@object` |
| The [PS5 3.20 export inventory](https://github.com/DNNDHH/PS5-3.20_Libs) | The name, per module. Every entry is marked `@function`, so it settles no kind |
| The console's module list ([asylumexp/ghostldr](https://github.com/asylumexp/ghostldr/blob/master/ghostldr/data/ps5_ps4_sysmodules.txt), firmware 13.60) | Which module exists, and in which of `/system/common/lib`, `/system/priv/lib` and `/system_ex/common_ex/lib` it is |
| The project's own [module table](../core/libs/prx/libSceSysmodule/ModuleTable.hpp) | The module ID a title imports by |

The SDK's 32 tables mark 759 symbols `@object`. This tree exports 114 of them on Linux and 148
on Windows; the Windows build exports 34 more, the C++ typeinfo and type-name objects
(`_ZTI*` and `_ZTS*`), which the ELF build does not export. Every one of them is a data
object rather than a function. An export the SDK marks `@object` and the tree exports as a
function is a defect: a consumer that resolves the NID and reads the object's address
reads the machine code of the stub, and there is no trap, so the read succeeds with
garbage. `tools/tests/test_data_object_exports.py` checks this for every built library.

The 3.20 inventory has a table per module, so it settles which module owns a name for the
264 of its 275 tables that name a module the console has. The 11 it does not
(`libSceCustomMusicCore`, `libSceDseehx`, `libSceFios2`, `libSceNpTcs`,
`libScePSNowGkp`, `WebAppBundle`, `gaikai-player`, `libfreetype`, `libharfbuzz`,
`libicu`, `libpng16`) are the third-party modules, whose exports are the upstream
project's own rather than the console's.

## Which module owns a name

A name belongs to the module of its own table, and the console's module list says which
modules exist. The two do not always agree, and the disagreement is the trap:

- The console has `libSceNpSessionSignaling.sprx`, `libSceNpSessionSignalingCrossplay.sprx`
  and `libSceNpRemotePlaySessionSignaling.sprx` as three modules. The 3.20 inventory has a
  table for the first and the third and **none for the Crossplay one**, and the five
  `sceNpSessionSignalingCrossplay*` names are in the NID name database only. Declaring them
  in `libSceNpSessionSignaling` mis-attributes them, and it does not fix a title: the
  import binds to the Crossplay module, which this tree does not provide. A name that names
  a family the console has as a module of its own belongs to that module.
- `/system_ex/common_ex/lib` is a different directory from `/system/common/lib`. A module
  there is not one of the system libraries a title mounts as its library directory, so its
  exports are not a title's imports. `libSceFacebook.Yoga.sprx` is in
  `/system_ex/common_ex/lib` and its exports are `YG*`, not `sce*`.

## What a call site settles

The PS5 uses the System V AMD64 calling convention: integer and pointer arguments in `rdi`, `rsi`, `rdx`, `rcx`, `r8`,
`r9`, then the stack; floating-point arguments in `xmm0`-`xmm7`; the result in `rax` or `xmm0`.

| Seen at the call site | Settles |
| --- | --- |
| Registers written right before the `call` | The argument count. A register set long before the call, or for another use, is not an argument; check several call sites |
| `mov %esi` / `mov %rsi`, `movzwl`, `movsbl` | The argument width and signedness |
| `lea -0x2030(%rbp), %rsi` | A pointer to a caller buffer; the stack layout gives its size |
| A value stored at the pointer before the call and read after it | An in/out argument (capacity in, size out) |
| `test %eax, %eax` / `cmp`, `js` after the call | An `int32_t` result and which values the title treats as failure |
| The result is never read | Nothing: the return type is not established ([libSceAgc](debt/libSceAgc.md)) |
| A log string that names the function (`"sceXxx() failed. Error code %#x"`) | Which import the call is, and that failures are SCE error codes |
| A first call with a null buffer, then a second one with a buffer of the returned size | A size query ([libSceNpTrophy2](debt/libSceNpTrophy2.md)) |

A call site doesn't settle what the library writes, which error codes it returns, its side effects, or the values a
title happens to accept. "The title continues if it gets 0" is not "the console returns 0". Everything that the call
site and the other sources leave open throws (`NotImplemented_nid_no_patch`), as in
[libSceAudioIn](debt/libSceAudioIn.md): the signature came from a call site, the meaning of the result did not, so the
export still throws. A silent stub is allowed only when it affects the UI ([CONTRIBUTING](../../CONTRIBUTING.md)): a
read that always reports no data, or a write that drops its data, is not UI.

## Finding the call sites

1. Unwrap the title's decrypted `eboot.bin` with `tools/unwrap_self.py`
   ([GAME_TESTING](GAME_TESTING.md)).
2. Relink it with `--registry` ([USAGE](../user/USAGE.md)). `app.registry.json` lists every import of the executable
   with its `nid`, `relocationType`, `targetOffset` (the GOT slot) and `callSites` (virtual addresses). Bundled modules'
   registries have no `callSites`. `tools/nid_names.py --name sceXxx` gives the NID of a name, and `--nid` the name of a
   NID (without the `#` suffix).
   - `R_X86_64_GLOB_DAT`: each call site is the `call *slot(%rip)` itself.
   - `R_X86_64_JUMP_SLOT`: the call site is the PLT stub (`jmp *slot(%rip)`); the callers are the `call <stub>`
     instructions.
3. Disassemble around the site. The ELF has no section headers, so `objdump -d` prints nothing; take the executable
   `LOAD` segment from `readelf -lW`, cut it out at its file offset and disassemble it at its virtual address:

   ```sh
   readelf -lW eboot.elf                      # executable LOAD: offset 0x4000, vaddr 0x0, filesz 0x1f36afc
   tail -c +$((0x4000 + 1)) eboot.elf | head -c $((0x1f36afc)) > text.bin
   objdump -D -b binary -m i386:x86-64 --adjust-vma=0x0 text.bin > text.dis
   grep -nE 'call +0x1f2e480$' text.dis       # callers of the JUMP_SLOT stub at 0x1f2e480
   ```

   A disassembler that loads the program headers (Ghidra, IDA) does the same.
4. Log strings near the call confirm which import it is: `strings -t x eboot.elf`, then the `lea` that loads that address.

The same steps work on a module: the code of a firmware module or of one in `sce_module/` gives the library's side of
the contract.

## Citing it

In the pull request and in the library's [debt](debt/) entry, say:

- Where it came from: the title ID and the call-site addresses (`PPSA03393, 0x76D132`), or the module and firmware
  version (`libSceRtc.sprx, firmware 13.60`).
- What each site showed: "`rsi` points to a 0x2000-byte stack buffer and `rdx` to its capacity, which the title reads
  back as the size".
- What was not verified: "read from disassembly, not measured on a console", "the return value is not read".

Quote only the instructions that show the claim, not whole functions. The code stays generic: a title ID belongs in the
debt entry, never in code or test names.

## Rules

- Work only from dumps of titles and firmware that you own. Never add, attach or link game files, firmware, decrypted
  binaries or keys in the repository, a pull request or an issue.
- Write the implementation from the contract you read (arguments, sizes, values, order, errors), not by translating the
  disassembly instruction by instruction or copying its structure. Rebuild data tables from a public source when one
  exists ([libSceIme](debt/libSceIme.md) rebuilds its codepage checks from Unicode's tables).
- The goal is interoperability: what a title needs from a system library to run. Nothing here is for bypassing
  licence, entitlement or online checks.
