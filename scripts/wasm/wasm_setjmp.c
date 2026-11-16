#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
// The setjmp helpers that LLVM 19 calls (__wasm_setjmp, __wasm_setjmp_test), as Emscripten 3.1.57 defines them in
// system/lib/compiler-rt/emscripten_setjmp.c. build.py links this into libwasm_setjmp.a when the toolchain's system
// libraries define only the older saveSetjmp: a clang that lowers setjmp the new way paired with 3.1.56 libraries.
// emscripten_longjmp is the same in both versions.
struct jmp_buf_impl {
  void* func_invocation_id;
  uint32_t label;
};
void __wasm_setjmp(void* env, uint32_t label, void* func_invocation_id) {
  struct jmp_buf_impl* jb = (struct jmp_buf_impl*)env;
  jb->func_invocation_id = func_invocation_id;
  jb->label = label;
}
uint32_t __wasm_setjmp_test(void* env, void* func_invocation_id) {
  struct jmp_buf_impl* jb = (struct jmp_buf_impl*)env;
  return jb->func_invocation_id == func_invocation_id ? jb->label : 0;
}
#ifdef __cplusplus
}
#endif
