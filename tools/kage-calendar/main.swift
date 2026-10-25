// Kage calendar helper (D2). A tiny app bundle so macOS can show its own calendar/reminders permission prompt
// (a Python process has no usage description and is denied silently). Read-only except the test calendar.
//   kage-calendar events <startISO> <endISO>     -> JSON events, recurrences expanded
//   kage-calendar reminders                      -> JSON incomplete reminders (due ≤ end of today or no date)
//   kage-calendar status | request
//   kage-calendar make-test-calendar <name> <json-events> | delete-calendar <name>
import EventKit
import Foundation

let store = EKEventStore()
let iso = ISO8601DateFormatter()
iso.formatOptions = [.withInternetDateTime]

func out(_ value: Any) {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
}
func fail(_ message: String) -> Never { out(["ok": false, "error": message]); exit(1) }
func wait(_ body: (@escaping (Bool, Error?) -> Void) -> Void) -> Bool {
    let sema = DispatchSemaphore(value: 0); var granted = false
    body { ok, _ in granted = ok; sema.signal() }
    _ = sema.wait(timeout: .now() + 120)
    return granted
}
func status(_ type: EKEntityType) -> String {
    switch EKEventStore.authorizationStatus(for: type) {
    case .fullAccess: return "full"
    case .writeOnly: return "write_only"
    case .denied: return "denied"
    case .restricted: return "restricted"
    default: return "not_determined"
    }
}
func needEvents() { if status(.event) != "full" && !wait({ store.requestFullAccessToEvents(completion: $0) }) { fail("calendar access not granted") } }
func needReminders() { if status(.reminder) != "full" && !wait({ store.requestFullAccessToReminders(completion: $0) }) { fail("reminders access not granted") } }

let args = Array(CommandLine.arguments.dropFirst())
switch args.first ?? "" {
case "status":
    out(["ok": true, "events": status(.event), "reminders": status(.reminder)])
case "request":
    needEvents(); needReminders()
    out(["ok": true, "events": status(.event), "reminders": status(.reminder)])
case "events":
    guard args.count == 3, let start = iso.date(from: args[1]), let end = iso.date(from: args[2]) else { fail("usage: events <startISO> <endISO>") }
    needEvents()
    let events = store.events(matching: store.predicateForEvents(withStart: start, end: end, calendars: nil))
        .sorted { $0.startDate < $1.startDate }
        .map { e -> [String: Any] in
            ["title": e.title ?? "", "start": iso.string(from: e.startDate), "end": iso.string(from: e.endDate),
             "all_day": e.isAllDay, "calendar": e.calendar.title, "location": e.location ?? "",
             "recurring": e.hasRecurrenceRules, "alarms_min": (e.alarms ?? []).map { Int(-$0.relativeOffset / 60) }]
        }
    out(["ok": true, "events": events])
case "reminders":
    needReminders()
    let cal = Calendar.current
    let endOfToday = cal.date(byAdding: .day, value: 1, to: cal.startOfDay(for: Date()))!
    let predicate = store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: endOfToday, calendars: nil)
    var items: [[String: Any]] = []
    let sema = DispatchSemaphore(value: 0)
    store.fetchReminders(matching: predicate) { reminders in
        for r in reminders ?? [] {
            let due = r.dueDateComponents.flatMap { cal.date(from: $0) }
            items.append(["title": r.title ?? "", "list": r.calendar.title, "due": due.map { iso.string(from: $0) } ?? ""])
        }
        sema.signal()
    }
    _ = sema.wait(timeout: .now() + 30)
    out(["ok": true, "reminders": items])
case "make-test-calendar":
    guard args.count == 3, let data = args[2].data(using: .utf8),
          let specs = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { fail("usage: make-test-calendar <name> <json>") }
    needEvents()
    let source = store.defaultCalendarForNewEvents?.source ?? store.sources.first { $0.sourceType == .local }!
    let calendar = EKCalendar(for: .event, eventStore: store)
    calendar.title = args[1]; calendar.source = source
    do { try store.saveCalendar(calendar, commit: true) } catch { fail("create calendar: \(error)") }
    for spec in specs {
        let e = EKEvent(eventStore: store)
        e.calendar = calendar; e.title = spec["title"] as? String ?? ""
        e.startDate = iso.date(from: spec["start"] as? String ?? "")!; e.endDate = iso.date(from: spec["end"] as? String ?? "")!
        e.isAllDay = spec["all_day"] as? Bool ?? false
        e.location = spec["location"] as? String
        if let minutes = spec["alarm_min"] as? Int { e.addAlarm(EKAlarm(relativeOffset: TimeInterval(-60 * minutes))) }
        if spec["daily"] as? Bool == true { e.addRecurrenceRule(EKRecurrenceRule(recurrenceWith: .daily, interval: 1, end: nil)) }
        do { try store.save(e, span: .futureEvents, commit: true) } catch { fail("save event: \(error)") }
    }
    out(["ok": true, "calendar": args[1], "source": source.title, "events": specs.count])
case "delete-calendar":
    guard args.count == 2 else { fail("usage: delete-calendar <name>") }
    needEvents()
    let matches = store.calendars(for: .event).filter { $0.title == args[1] }
    guard matches.count == 1 else { fail("expected exactly one calendar named \(args[1]), found \(matches.count)") }
    do { try store.removeCalendar(matches[0], commit: true) } catch { fail("delete: \(error)") }
    out(["ok": true, "deleted": args[1]])
default:
    fail("unknown command")
}
