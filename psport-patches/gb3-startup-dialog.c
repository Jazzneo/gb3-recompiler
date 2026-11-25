/* Exercise the actual dialog service, with an overlay and clock test double.
 * Compile with function/data sections and --gc-sections to omit unrelated services. */
#include "../src/system/runtime_services.c"
#include <assert.h>

static const char *test_title="CUSA07651";
static int show_prompt, overlay_opens;
static const char signin[]="For information on and update of additional contents to GUNDAM PERFECT GAMES "
    "signing in to PSN is required. Sign in into PSN?";

const char *runtime_content_title_id(void) { return test_title; }
uint32_t runtime_process_sdk_version(void) { return 0x04000000u; }
uint64_t ps_host_time_monotonic_ns(void) { return 1000000000u; }
int runtime_env_int(const char *name,int fallback) {
    return !strcmp(name,"PS_GB3_PSN_PROMPT") ? show_prompt : fallback;
}
void runtime_calls_add_summary(RuntimeSummary fn) { (void)fn; }
int psport_gpu_message_begin(const char *text,int system,const PsMessageButton *buttons,int count,int focus,int cancel) {
    (void)text; (void)system; (void)buttons; (void)count; (void)focus; (void)cancel;
    ++overlay_opens; return 1;
}
int psport_gpu_message_poll(void) { return 0; }
void psport_gpu_message_end(void) {}

static void check(const char *title,const char *text,int button_type,int opt_out,int skipped) {
    uint8_t param[0x88]={0},user[0x30]={0};
    uint64_t base_size=0x30,param_size=sizeof(param);
    uint32_t magic=0xC0D1A109u+(uint32_t)(uintptr_t)param;
    int32_t mode=MSG_MODE_USER;
    const void *p_user=user;
    memcpy(param,&base_size,8); memcpy(param+0x2c,&magic,4);
    memcpy(param+0x30,&param_size,8); memcpy(param+0x38,&mode,4);
    memcpy(param+0x40,&p_user,sizeof(p_user));
    memcpy(user,&button_type,4); memcpy(user+8,&text,sizeof(text));
    test_title=title; show_prompt=opt_out; overlay_opens=0;
    assert(msg_init()==0);
    assert(msg_open(param)==0);
    assert(s_dialogs[1].status==2);
    assert(overlay_opens==!skipped);
    int32_t result[11]={0};
    if (skipped) {
        assert(msg_status()==3);
        assert(msg_result(result)==0);
        assert(result[0]==MSG_MODE_USER && result[1]==MSG_RESULT_OK && result[2]==2);
    } else {
        assert(msg_status()==2);
        assert(msg_result(result)==DIALOG_NOT_FINISHED);
        assert(msg_close()==0);
    }
    assert(msg_term()==0);
}

int main(void) {
    check("CUSA07651",signin,MSG_BUTTONS_YESNO,0,1);
    check("CUSA07651",signin,MSG_BUTTONS_YESNO,1,0);
    check("CUSA00000",signin,MSG_BUTTONS_YESNO,0,0);
    check("CUSA07651","Overwrite existing save data?",MSG_BUTTONS_YESNO,0,0);
    check("CUSA07651","Sign in into PSN?",MSG_BUTTONS_YESNO,0,0);
    check("CUSA07651",signin,MSG_BUTTONS_OK_CANCEL,0,0);
    puts("PASS: targeted prompt returns No without overlay; opt-out, other titles, save questions and other button types remain interactive.");
    return 0;
}
