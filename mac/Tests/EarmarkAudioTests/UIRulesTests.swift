import Testing
@testable import EarmarkApp
@testable import EarmarkAudio
@testable import EarmarkUI

@Suite struct UIRulesTests {
    @Test func spaceReachesPushToTalkOnlyWhenTheFieldIsEmpty() {
        #expect(KeyMonitor.handlesKey(.space, textFieldFocused: true, fieldIsEmpty: true))
        #expect(!KeyMonitor.handlesKey(.space, textFieldFocused: true, fieldIsEmpty: false))
    }

    @Test func otherKeysStayWithTheTextField() {
        for key in [KeyMonitor.Key.character("r"), .left, .right, .up, .down] {
            #expect(!KeyMonitor.handlesKey(key, textFieldFocused: true, fieldIsEmpty: true))
        }
    }

    @Test func everyKeyWorksWhenNoTextFieldIsFocused() {
        #expect(KeyMonitor.handlesKey(.space, textFieldFocused: false, fieldIsEmpty: false))
        #expect(KeyMonitor.handlesKey(.character("r"), textFieldFocused: false, fieldIsEmpty: true))
    }

    @Test func ringStepGrowsWithReach() {
        #expect(MapView.ringStep(reach: 1.0) == 0.25)
        #expect(MapView.ringStep(reach: 1.5) == 0.25)
        #expect(MapView.ringStep(reach: 2.0) == 0.5)
        #expect(MapView.ringStep(reach: 3.0) == 0.5)
        #expect(MapView.ringStep(reach: 5.0) == 1)
    }

    @Test func ringLabelsUseCentimetersThenMeters() {
        #expect(MapView.ringLabel(0.25) == "25 cm")
        #expect(MapView.ringLabel(0.75) == "75 cm")
        #expect(MapView.ringLabel(1) == "1 m")
        #expect(MapView.ringLabel(3) == "3 m")
    }

    @Test func headTrackingRetriesOnlyWhileDisconnectedOrWaiting() {
        let p = HeadphoneMotionTracker.retryPeriod
        #expect(HeadphoneMotionTracker.shouldRetry(state: .disconnected, now: 10 + p, lastRestartAt: 10))
        #expect(HeadphoneMotionTracker.shouldRetry(state: .waiting, now: 10 + p, lastRestartAt: 10))
        #expect(!HeadphoneMotionTracker.shouldRetry(state: .disconnected, now: 10 + p - 0.5, lastRestartAt: 10))
        #expect(!HeadphoneMotionTracker.shouldRetry(state: .connected, now: 100, lastRestartAt: 10))
        #expect(!HeadphoneMotionTracker.shouldRetry(state: .notAuthorized, now: 100, lastRestartAt: 10))
    }
}
