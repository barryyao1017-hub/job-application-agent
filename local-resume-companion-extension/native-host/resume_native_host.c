#include <dirent.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#ifndef CONFIG_PATH
#define CONFIG_PATH "config.json"
#endif
#ifndef QUEUE_DIR
#define QUEUE_DIR "attach-queue"
#endif
// The single-slot file older enqueue-attach.js versions write; still honored
// so a checkout that predates the queue directory keeps working.
#ifndef QUEUE_PATH
#define QUEUE_PATH "attach-target-url.txt"
#endif
// Entries a worker left behind stop matching after this long.
#define ENTRY_MAX_AGE_SECONDS (30 * 60)

static const char base64_table[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static int config_resume_path(char *output, size_t output_size) {
  FILE *config = fopen(CONFIG_PATH, "r");
  if (!config) return 0;
  char data[8192] = {0};
  size_t count = fread(data, 1, sizeof(data) - 1, config);
  fclose(config);
  if (!count) return 0;
  const char *key = strstr(data, "\"approved_resume_path\"");
  if (!key) return 0;
  const char *start = strchr(key + 23, '"');
  if (!start) return 0;
  start += 1;
  const char *end = strchr(start, '"');
  if (!end || (size_t)(end - start) >= output_size) return 0;
  memcpy(output, start, (size_t)(end - start));
  output[end - start] = '\0';
  return output[0] != '\0';
}

static char *encode_base64(const unsigned char *data, size_t size) {
  size_t output_size = 4 * ((size + 2) / 3);
  char *output = malloc(output_size + 1);
  if (!output) return NULL;
  size_t source = 0, destination = 0;
  while (source < size) {
    unsigned int a = data[source++];
    unsigned int b = source < size ? data[source++] : 0;
    unsigned int c = source < size ? data[source++] : 0;
    unsigned int value = (a << 16) | (b << 8) | c;
    output[destination++] = base64_table[(value >> 18) & 63];
    output[destination++] = base64_table[(value >> 12) & 63];
    output[destination++] = source - 1 < size ? base64_table[(value >> 6) & 63] : '=';
    output[destination++] = source < size + 1 ? base64_table[value & 63] : '=';
  }
  size_t remainder = size % 3;
  if (remainder) {
    output[output_size - 1] = '=';
    if (remainder == 1) output[output_size - 2] = '=';
  }
  output[output_size] = '\0';
  return output;
}

// Claims one queued entry whose URL appears in the payload by renaming it to
// a name unique to this process. rename() is atomic, so when several hosts
// race for the same entry exactly one wins; the rest see ENOENT and move on.
static int claim_entry(const char *entry, const char *payload, char *claimed, size_t claimed_size) {
  struct stat info;
  if (stat(entry, &info) != 0 || !S_ISREG(info.st_mode)) return 0;
  if (time(NULL) - info.st_mtime > ENTRY_MAX_AGE_SECONDS) {
    unlink(entry);
    return 0;
  }
  char target[2048] = {0};
  FILE *file = fopen(entry, "r");
  if (!file) return 0;
  if (!fgets(target, sizeof(target), file)) target[0] = '\0';
  fclose(file);
  target[strcspn(target, "\r\n")] = '\0';
  if (!target[0] || !strstr(payload, target)) return 0;
  snprintf(claimed, claimed_size, "%s.claimed-%ld", entry, (long)getpid());
  return rename(entry, claimed) == 0;
}

static int claim_queued(const char *payload, char *entry, size_t entry_size, char *claimed, size_t claimed_size) {
  DIR *queue = opendir(QUEUE_DIR);
  if (queue) {
    struct dirent *item;
    while ((item = readdir(queue))) {
      size_t name_length = strlen(item->d_name);
      if (name_length < 5 || strcmp(item->d_name + name_length - 4, ".url") != 0) continue;
      snprintf(entry, entry_size, "%s/%s", QUEUE_DIR, item->d_name);
      if (claim_entry(entry, payload, claimed, claimed_size)) {
        closedir(queue);
        return 1;
      }
    }
    closedir(queue);
  }
  snprintf(entry, entry_size, "%s", QUEUE_PATH);
  return claim_entry(entry, payload, claimed, claimed_size);
}

int main(void) {
  uint32_t length = 0;
  if (fread(&length, sizeof(length), 1, stdin) != 1 || length > 1024 * 1024) return 1;
  static char payload[1048577];
  if (fread(payload, 1, length, stdin) != length) return 1;
  payload[length] = '\0';
  char resume[4096] = {0};
  config_resume_path(resume, sizeof(resume));
  char entry[4096] = {0}, claimed[4200] = {0};
  int claim = strstr(payload, "claim-attachment") && resume[0] && access(resume, R_OK) == 0 &&
              claim_queued(payload, entry, sizeof(entry), claimed, sizeof(claimed));
  char *reply = NULL;
  if (claim) {
    FILE *file = fopen(resume, "rb");
    if (file && fseek(file, 0, SEEK_END) == 0) {
      long size = ftell(file);
      rewind(file);
      unsigned char *bytes = size > 0 ? malloc((size_t)size) : NULL;
      if (bytes && fread(bytes, 1, (size_t)size, file) == (size_t)size) {
        char *encoded = encode_base64(bytes, (size_t)size);
        if (encoded) {
          size_t needed = strlen(encoded) + 80;
          reply = malloc(needed);
          if (reply) snprintf(reply, needed, "{\"fileName\":\"Jiayi_Yao_resume.docx\",\"base64\":\"%s\"}", encoded);
          free(encoded);
        }
      }
      free(bytes);
      fclose(file);
    }
    // Consume the entry only once the reply exists; otherwise put it back.
    if (reply) unlink(claimed);
    else rename(claimed, entry);
  }
  if (!reply) reply = strdup("{\"error\":\"No matching approved resume attachment is queued\"}");
  uint32_t reply_length = (uint32_t)strlen(reply);
  if (fwrite(&reply_length, sizeof(reply_length), 1, stdout) != 1) return 1;
  if (fwrite(reply, 1, reply_length, stdout) != reply_length) return 1;
  free(reply);
  return fflush(stdout) == 0 ? 0 : 1;
}
