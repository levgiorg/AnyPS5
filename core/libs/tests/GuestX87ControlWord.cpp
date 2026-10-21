#include "prx/libkernel/Pthread/include/Pthread.hpp"
#include <cstdint>
#include <cstring>
#include <future>
#include <iostream>
#include <stdexcept>

extern "C" int APS5_VABI scePthreadCreate(Pthread* thread, const PthreadAttr* attr, PthreadEntry entry, void* arg, const char* name);
extern "C" int APS5_VABI scePthreadJoin(Pthread thread, void** retval);
extern "C" long double APS5_VABI asinl_nid_postfix(long double x);

static constexpr std::uint16_t GUEST_CONTROL_WORD = 0x37f;
static constexpr std::uint16_t HOST_THREAD_CONTROL_WORD = 0x027f;
static constexpr std::uint64_t CONSOLE_ASINL_MANTISSA = 0xd91a98ae3406e041ull;

static std::uint16_t ReadControlWord() {
    std::uint16_t control = 0;
    asm volatile("fnstcw %0" : "=m"(control));
    return control;
}

static void WriteControlWord(std::uint16_t control) {
    asm volatile("fldcw %0" : : "m"(control));
}

static std::uint64_t Significand(long double value) {
    unsigned char bytes[sizeof(long double)];
    std::memcpy(bytes, &value, sizeof(bytes));
    std::uint64_t significand = 0;
    for (int index = 7; index >= 0; --index) significand = (significand << 8) | bytes[index];
    return significand;
}

struct ControlWordScope {
    std::uint16_t saved;
    ControlWordScope() : saved(ReadControlWord()) {}
    ~ControlWordScope() { WriteControlWord(saved); }
    ControlWordScope(const ControlWordScope&) = delete;
    ControlWordScope& operator=(const ControlWordScope&) = delete;
};

struct Observation {
    std::uint16_t controlWord = 0;
    std::uint64_t mantissa = 0;
};

struct ThreadContext {
    Pthread thread = nullptr;
    std::promise<Observation> observed;
};

static void* APS5_VABI ObserveControlWord(void* arg) {
    auto& context = *static_cast<ThreadContext*>(arg);
    Observation observation;
    observation.controlWord = ReadControlWord();
    observation.mantissa = Significand(asinl_nid_postfix(0.75L));
    context.observed.set_value(observation);
    return arg;
}

static Observation RunGuestThread() {
    ThreadContext context;
    if (scePthreadCreate(&context.thread, nullptr, ObserveControlWord, &context, nullptr) != 0)
        throw std::runtime_error("Guest thread creation failed");
    const Observation observation = context.observed.get_future().get();
    void* result = nullptr;
    if (scePthreadJoin(context.thread, &result) != 0)
        throw std::runtime_error("Guest thread join failed");
    if (result != &context) throw std::runtime_error("Guest thread return value was lost");
    return observation;
}

static void CheckGuestThread() {
    const Observation observation = RunGuestThread();
    if (observation.controlWord != GUEST_CONTROL_WORD)
        throw std::runtime_error("Guest thread x87 control word is not the console value 0x37f");
    if (observation.mantissa != CONSOLE_ASINL_MANTISSA)
        throw std::runtime_error("Guest thread asinl does not return the console mantissa");
}

int main() {
    const std::uint16_t hostControlWord = ReadControlWord();
    CheckGuestThread();
    if (ReadControlWord() != hostControlWord)
        throw std::runtime_error("Guest execution changed the host x87 control word");
    {
        ControlWordScope scope;
        WriteControlWord(HOST_THREAD_CONTROL_WORD);
        if (ReadControlWord() != HOST_THREAD_CONTROL_WORD)
            throw std::runtime_error("Host x87 control word was not changed for the creator check");
        CheckGuestThread();
    }
    if (ReadControlWord() != hostControlWord)
        throw std::runtime_error("Host x87 control word was not restored after the creator check");
    std::cout << "PASS: guest threads start with the console x87 control word 0x37f whatever the creating thread holds; asinl keeps the console mantissa; the host control word is preserved\n";
    return 0;
}
