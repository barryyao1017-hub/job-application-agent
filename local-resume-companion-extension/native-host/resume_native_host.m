#import <Foundation/Foundation.h>
#include <stdint.h>
#include <stdio.h>

#ifndef RESUME_ROOT
#error RESUME_ROOT must name the installation directory
#endif

static NSDictionary *failure(NSString *message) { return @{ @"error": message }; }

static NSDictionary *handle(NSDictionary *message) {
    NSString *root = @RESUME_ROOT;
    NSString *queue = [root stringByAppendingPathComponent:@"local-resume-companion-extension/attach-target-url.txt"];
    NSString *lock = [queue stringByAppendingString:@".lock"];
    NSFileManager *fm = NSFileManager.defaultManager;
    NSError *error = nil;
    if (![fm createDirectoryAtPath:lock withIntermediateDirectories:NO attributes:nil error:&error]) {
        return failure(@"Attachment queue unavailable or busy");
    }
    @try {
        if (![fm fileExistsAtPath:queue]) return @{ @"pending": @YES };
        NSData *data = [NSData dataWithContentsOfFile:queue];
        NSDictionary *target = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
        if (![target isKindOfClass:NSDictionary.class] || ![target[@"version"] isEqual:@2] ||
            ![target[@"requestId"] isKindOfClass:NSString.class] ||
            ![target[@"url"] isKindOfClass:NSString.class] ||
            !([target[@"url"] hasPrefix:@"https://"] || [target[@"url"] hasPrefix:@"http://"])) {
            return failure(@"Invalid attachment request; enqueue a fresh request");
        }
        if ([message[@"type"] isEqual:@"peek-attachment"]) return @{ @"target": target };
        if (![message[@"type"] isEqual:@"claim-attachment"] ||
            ![message[@"requestId"] isEqual:target[@"requestId"]]) return failure(@"Attachment request changed; inspect again");
        if (![message[@"url"] isEqual:target[@"url"]]) return failure(@"Document URL does not match");
        if (target[@"selector"] &&
            (![target[@"selector"] isKindOfClass:NSString.class] || ![target[@"selector"] length] ||
             ![target[@"tabId"] isKindOfClass:NSNumber.class] || ![target[@"frameId"] isKindOfClass:NSNumber.class] ||
             ![message[@"tabId"] isEqual:target[@"tabId"]] || ![message[@"frameId"] isEqual:target[@"frameId"]])) {
            return failure(@"Tab, frame, or selector does not match");
        }
        NSData *configData = [NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:@"config.json"]];
        NSDictionary *config = configData ? [NSJSONSerialization JSONObjectWithData:configData options:0 error:nil] : nil;
        NSString *path = [config isKindOfClass:NSDictionary.class] ? config[@"approved_resume_path"] : nil;
        if (![path isKindOfClass:NSString.class]) return failure(@"Approved résumé configuration unavailable");
        path = path.stringByExpandingTildeInPath;
        NSData *resume = [NSData dataWithContentsOfFile:path];
        if (!resume.length || resume.length > 700000) return failure(@"Approved résumé unreadable, empty, or too large");
        if (![fm removeItemAtPath:queue error:nil]) return failure(@"Could not consume attachment request");
        return @{ @"requestId": target[@"requestId"], @"fileName": path.lastPathComponent,
                  @"base64": [resume base64EncodedStringWithOptions:0] };
    } @finally {
        [fm removeItemAtPath:lock error:nil];
    }
}

int main(void) {
    @autoreleasepool {
        uint32_t length = 0;
        if (fread(&length, sizeof(length), 1, stdin) != 1 || length > 1048576) return 1;
        NSMutableData *body = [NSMutableData dataWithLength:length];
        if (fread(body.mutableBytes, 1, length, stdin) != length) return 1;
        id message = [NSJSONSerialization JSONObjectWithData:body options:0 error:nil];
        NSDictionary *reply = [message isKindOfClass:NSDictionary.class] ? handle(message) : failure(@"Invalid native message");
        NSData *result = [NSJSONSerialization dataWithJSONObject:reply options:0 error:nil];
        length = (uint32_t)result.length;
        if (fwrite(&length, sizeof(length), 1, stdout) != 1 || fwrite(result.bytes, 1, length, stdout) != length) return 1;
        return fflush(stdout) == 0 ? 0 : 1;
    }
}
