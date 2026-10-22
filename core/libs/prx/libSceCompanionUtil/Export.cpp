#include <cstdint>
#include <cstddef>
#include "SceTypes.hpp"
#include "prx/libc/include/General.hpp"

extern "C" {

int APS5_VABI sceCompanionUtilGetEvent() {
    return static_cast<int>(0x80AD0008);
}

int APS5_VABI sceCompanionUtilGetRemoteOskEvent(void) {
    NotImplemented_nid_no_patch(__func__);
    return 0;
}

int APS5_VABI sceCompanionUtilInitialize(void) {
    NotImplemented_nid_no_patch(__func__);
    return 0;
}

int APS5_VABI sceCompanionUtilOptParamInitialize(void) {
    NotImplemented_nid_no_patch(__func__);
    return 0;
}

int APS5_VABI sceCompanionUtilTerminate(void) {
    NotImplemented_nid_no_patch(__func__);
    return 0;
}

}
