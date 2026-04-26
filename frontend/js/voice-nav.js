'use strict';

// ── 音声ナビゲーション モジュール ─────────────────────────────────────────
// 音声・文字・振動を同一ソースから同時出力する。
// voiceNav.announce(message) / announceStep() / announceApproach() を各ナビ
// イベントから呼ぶだけで動作する。音声OFFでも文字案内は常に表示される。

const voiceNav = (() => {

    // ── 設定パラメータ（管理画面で上書き可能な値のフォールバック）────────────────
    const CONFIG = {
        approachDistanceMeters:    30,     // 接近予告を出す距離
        finalReminderDistanceM:    5,      // 直前リマインドを出す距離
        stopGuardDistanceM:        3,      // 停止時の再発話を防ぐ最小距離
        duplicateSpeechCooldownMs: 10000,  // 通常の重複発話防止（ms）
        offRouteSpeechCooldownMs:  10000,  // 逸脱警告の再発話間隔（ms）
        textDisplayDurationMs:     5000,   // 通常案内の文字表示時間（ms）
        speechRate:                1.1,    // 読み上げ速度
    };

    // getRuntimeConfigValue（config.js で定義）から数値設定を読む共通ヘルパー。
    // config.js が先にロードされていない環境では fallback を使う。
    function _voiceConfigNumber(key, fallback) {
        if (typeof getRuntimeConfigValue !== 'function') return fallback;
        const v = Number(getRuntimeConfigValue(key, fallback));
        return Number.isFinite(v) && v > 0 ? v : fallback;
    }

    // ── 振動パターン ─────────────────────────────────────────────────────────
    const HAPTIC_PATTERNS = {
        start:       [80],               // ナビ開始: 短く1回
        approach:    [120],              // 接近予告: 短く1回
        offRoute:    [150, 80, 150],     // 逸脱: 2回、強め
        backOnRoute: [60, 60, 60],       // ルート復帰: 3回、軽め
        arrival:     [80, 60, 80, 60, 180], // 到着: 終了感
    };

    // ── 内部ステート ─────────────────────────────────────────────────────────
    const state = {
        enabled:         true,   // 音声ON/OFF（文字案内は常に動作）
        lastMessageId:   null,
        lastMessageText: null,
        lastSpokenAt:    0,
        lastCategory:        null,
        lastAnnouncedType:   null,
        lastCrossingId:     null,
        lastFinalReminderId: null,
        instructionContext: null,
        hideTimer:       null,
    };

    const hapticsState = {
        enabled:         true,   // 振動ON/OFF（音声とは独立して制御可）
        lastPatternKey:  null,
        lastVibratedAt:  0,
    };

    // ── 日本語音声選択 ───────────────────────────────────────────────────────
    let _selectedVoice = null;

    function _selectJapaneseVoice() {
        if (!window.speechSynthesis) return null;
        const voices = window.speechSynthesis.getVoices();
        if (!voices || voices.length === 0) return null;

        // 優先順位: iOS Kyoko/O-ren → Google 日本語 → Haruka → ja-JP の最初
        const preferred = ['Kyoko', 'O-ren', 'Haruka', 'Google 日本語', 'Google Japanese'];
        for (const name of preferred) {
            const v = voices.find(v => v.name.includes(name));
            if (v) {
                _selectedVoice = v;
                console.info('[Voice] selected:', v.name);
                return v;
            }
        }
        // フォールバック: lang が ja-JP の最初の音声
        const fallback = voices.find(v => v.lang === 'ja-JP') || null;
        _selectedVoice = fallback;
        console.info('[Voice] selected (fallback):', fallback?.name ?? 'none');
        return fallback;
    }

    // getVoices() は非同期で返ることがあるため voiceschanged でも初期化
    if (typeof window !== 'undefined' && window.speechSynthesis) {
        window.speechSynthesis.onvoiceschanged = () => { _selectJapaneseVoice(); };
        _selectJapaneseVoice(); // 同期で返る環境（Chrome等）向けに即実行
    }

    // ── 音声ログ発行（BroadcastChannel + localStorage）────────────────────────
    // 管理画面の Logs タブ Voice モードで受信・表示される。
    function _emitVoiceLog(detail) {
        try {
            const ch = new BroadcastChannel('ohg-voice-log');
            ch.postMessage(detail);
            ch.close();
        } catch (_) {}
        try {
            const stored = JSON.parse(localStorage.getItem('ohg_voice_log') || '[]');
            stored.push(detail);
            if (stored.length > 100) stored.splice(0, stored.length - 100);
            localStorage.setItem('ohg_voice_log', JSON.stringify(stored));
        } catch (_) {}
    }

    // ── iOS Safari 音声ロック解除 ────────────────────────────────────────────
    // iOS では speechSynthesis.speak() がユーザー操作なしにブロックされる。
    // ナビ開始ボタン押下（ユーザー操作）のタイミングで呼ぶことで解除する。
    function _unlockSpeechSynthesis() {
        if (!window.speechSynthesis) return;
        const utter = new SpeechSynthesisUtterance('');
        utter.volume = 0;
        window.speechSynthesis.speak(utter);
        window.speechSynthesis.cancel();
    }

    // ── 重複発話チェック ─────────────────────────────────────────────────────
    function _shouldAnnounce(message) {
        if (state.lastMessageId === message.id) return false;
        const cooldown = message.category === 'warning'
            ? _voiceConfigNumber('voice.cooldown_ms', CONFIG.offRouteSpeechCooldownMs)
            : _voiceConfigNumber('voice.cooldown_ms', CONFIG.duplicateSpeechCooldownMs);
        const isHigh = message.priority === 'high';
        const elapsed = Date.now() - state.lastSpokenAt;
        if (!isHigh && elapsed < cooldown) return false;
        // 同一テキスト（高優先でも）はクールダウン内に再発話しない
        if (state.lastMessageText === message.text && elapsed < cooldown) return false;
        // 同一タイプ（crossing/turn等）もクールダウン内に再発話しない（高優先は免除）
        if (!isHigh && message.msgType && state.lastAnnouncedType === message.msgType &&
            elapsed < cooldown) return false;
        return true;
    }

    // ── SpeechSynthesis 発話 ─────────────────────────────────────────────────
    function _speak(text) {
        if (!window.speechSynthesis || !text) return;
        window.speechSynthesis.cancel();
        const utter  = new SpeechSynthesisUtterance(text);
        utter.lang   = 'ja-JP';
        utter.rate   = _voiceConfigNumber('voice.rate', CONFIG.speechRate);
        utter.pitch  = 1.0;
        utter.volume = 1.0;
        if (_selectedVoice) utter.voice = _selectedVoice;
        window.speechSynthesis.speak(utter);
    }

    function _distanceMeters(a, b) {
        const lat1 = Number(a?.lat);
        const lon1 = Number(a?.lng ?? a?.lon);
        const lat2 = Number(b?.lat);
        const lon2 = Number(b?.lng ?? b?.lon);
        if (![lat1, lon1, lat2, lon2].every(Number.isFinite)) return Infinity;
        const rad = Math.PI / 180;
        const dLat = (lat2 - lat1) * rad;
        const dLon = (lon2 - lon1) * rad;
        const s1 = Math.sin(dLat / 2);
        const s2 = Math.sin(dLon / 2);
        const h = s1 * s1 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * s2 * s2;
        return 6371000 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
    }

    function _stepType(rawText) {
        const text = String(rawText || '');
        if (/右|right/i.test(text)) return 'turn_right';
        if (/左|left/i.test(text)) return 'turn_left';
        if (/目的地|到着/.test(text)) return 'arrival';
        return 'straight';
    }

    function _stepVoiceText(rawText) {
        const type = _stepType(rawText);
        if (type === 'turn_right') return '右です';
        if (type === 'turn_left')  return '左です';
        if (type === 'arrival')    return 'もうすぐ到着です';
        return '直進です';
    }

    function _findUpcomingCrossing(position, route) {
        const crossings = Array.isArray(route?.__pedestrianSafety?.crossings)
            ? route.__pedestrianSafety.crossings
            : [];
        let nearest = null;
        for (const crossing of crossings) {
            const point = crossing?.point;
            const dist = _distanceMeters(position, point);
            if (!Number.isFinite(dist) || dist > CONFIG.approachDistanceMeters) continue;
            if (!nearest || dist < nearest.distanceM) {
                nearest = { crossing, distanceM: dist };
            }
        }
        return nearest;
    }

    function _crossingVoiceMessage(upcoming) {
        const classification = upcoming?.crossing?.classification || {};
        const signalized = !!classification.signalizedCrossing || classification.crossingType === 'signalized';
        const marked = !!classification.markedCrossing || !!classification.crosswalkNearby;
        if (signalized) return { type: 'crossing', text: '信号を渡ります', signalized, marked };
        if (marked)     return { type: 'crossing', text: '横断歩道を渡ります', signalized, marked };
        return { type: 'crossing', text: 'ここで横断、注意', signalized, marked };
    }

    // 5m直前リマインド用テキスト（「この先」→「ここで」に変える）
    function _finalCrossingText(upcoming) {
        const cls = upcoming?.crossing?.classification || {};
        const signalized = !!cls.signalizedCrossing || cls.crossingType === 'signalized';
        const marked = !!cls.markedCrossing || !!cls.crosswalkNearby;
        if (signalized) return 'ここで信号を渡ります';
        if (marked)     return 'ここで横断歩道を渡ります';
        return 'ここで横断、注意';
    }

    function _finalTurnText(rawText) {
        const type = _stepType(rawText);
        if (type === 'turn_right') return 'ここで右です';
        if (type === 'turn_left')  return 'ここで左です';
        return null;
    }

    function _getTurnInstruction(position) {
        const stepEl = document.querySelector('li.nav-step-current[data-step-lat]');
        if (!stepEl) return null;
        const stepPoint = {
            lat: parseFloat(stepEl.dataset.stepLat),
            lng: parseFloat(stepEl.dataset.stepLon)
        };
        const distToStep = _distanceMeters(position, stepPoint);
        if (distToStep > CONFIG.approachDistanceMeters) return null;
        const rawText = stepEl.textContent.split('（')[0].trim();
        return {
            rawText,
            stepId: `${stepEl.dataset.stepLat},${stepEl.dataset.stepLon}`,
            distanceM: distToStep
        };
    }

    function _hasPriorityCrossingInContext() {
        const context = state.instructionContext;
        if (!context || Date.now() - context.updatedAt > 1500) return false;
        return !!_findUpcomingCrossing(context.position, context.route);
    }

    // ── 振動通知 ─────────────────────────────────────────────────────────────
    // navigator.vibrate() 非対応端末（iPhone Safari 等）では静かに無効化する
    function _canVibrate() {
        return typeof navigator !== 'undefined' &&
               typeof navigator.vibrate === 'function';
    }

    // patternKey: クールダウンの識別キー
    // pattern:    振動パターン（ms配列）
    // cooldownMs: 同一キーの再振動を抑制する時間
    function _vibrate(patternKey, pattern, cooldownMs) {
        if (!hapticsState.enabled) return;
        if (!_canVibrate()) return;
        const now = Date.now();
        if (hapticsState.lastPatternKey === patternKey &&
            now - hapticsState.lastVibratedAt < cooldownMs) return;
        navigator.vibrate(pattern);
        hapticsState.lastPatternKey = patternKey;
        hapticsState.lastVibratedAt = now;
    }

    // メッセージカテゴリ/IDから振動パターンを選択して実行
    function _vibrateForMessage(message) {
        if (message.category === 'arrival') {
            _vibrate('arrival', HAPTIC_PATTERNS.arrival, 15000);
        } else if (message.category === 'warning') {
            _vibrate('off-route', HAPTIC_PATTERNS.offRoute, 10000);
        } else if (message.id === 'nav-start') {
            _vibrate('nav-start', HAPTIC_PATTERNS.start, 5000);
        } else if (message.id === 'nav-back-on-route') {
            _vibrate('nav-back-on-route', HAPTIC_PATTERNS.backOnRoute, 5000);
        } else if (message.id && message.id.startsWith('pre-')) {
            // 接近予告（pre-xxxxx）: stepId 単位でクールダウン
            _vibrate(`approach-${message.id}`, HAPTIC_PATTERNS.approach, 5000);
        }
    }

    // ── テキスト案内バー更新 ─────────────────────────────────────────────────
    function _updateDisplay(message) {
        const bar  = document.getElementById('nav-announcement-bar');
        const span = document.getElementById('nav-announcement-text');
        if (!bar || !span) return;

        span.textContent     = message.displayText || message.text;
        bar.dataset.category = message.category || 'maneuver';
        bar.style.display    = 'flex';

        if (state.hideTimer) { clearTimeout(state.hideTimer); state.hideTimer = null; }
        if (message.category !== 'warning' && message.category !== 'arrival') {
            state.hideTimer = setTimeout(
                () => { bar.style.display = 'none'; },
                CONFIG.textDisplayDurationMs
            );
        }
    }

    // ── 公開API ──────────────────────────────────────────────────────────────
    return {

        get enabled()  { return state.enabled; },
        get config()   { return CONFIG; },

        // iOS Safari 音声ロック解除（ナビ開始ボタン押下時に呼ぶ）
        unlockSpeech() { _unlockSpeechSynthesis(); },

        setInstructionContext(position, route) {
            state.instructionContext = {
                position,
                route,
                updatedAt: Date.now()
            };
        },

        // 汎用アナウンス（ナビ開始・逸脱・到着など）
        announce(message) {
            if (!message || !message.text) return false;
            if (!_shouldAnnounce(message)) return false;

            // 到着時は先行音声を即停止してから発話
            if (message.category === 'arrival' && window.speechSynthesis) {
                window.speechSynthesis.cancel();
            }

            _updateDisplay(message);
            if (state.enabled) _speak(message.text);
            _vibrateForMessage(message);   // 音声ON/OFFに関わらず振動は独立動作

            state.lastMessageId      = message.id;
            state.lastMessageText    = message.text;
            state.lastSpokenAt       = Date.now();
            state.lastCategory       = message.category || null;
            state.lastAnnouncedType  = message.msgType  || null;
            _emitVoiceLog({
                ts:       new Date().toISOString(),
                type:     message.msgType  || 'voice',
                text:     message.text,
                priority: message.priority || 'normal',
            });
            return true;
        },

        // ステップ変化時（routing.js から呼ぶ）
        // distanceM: 現在地から次のステップまでの距離（メートル）、省略可
        announceStep(rawText, stepId, distanceM = null) {
            if (!rawText) return;
            if (Number.isFinite(distanceM) && distanceM > CONFIG.approachDistanceMeters) return;
            if (_hasPriorityCrossingInContext()) {
                console.log('[voice] skip=turn priority=crossing');
                return;
            }
            const type = _stepType(rawText);
            const spokenText = _stepVoiceText(rawText);
            console.log(`[voice] text="${spokenText}" type=${type} dist=${Number.isFinite(distanceM) ? Math.round(distanceM) : 'unknown'}m`);
            this.announce({
                id:          `step-${stepId}`,
                text:        spokenText,
                displayText: rawText,
                category:    'maneuver',
                msgType:     type,
                priority:    'normal',
            });
        },

        // 接近予告（曲がり角の手前で "まもなく〇〇" と予告）
        announceApproach(rawText, stepId) {
            if (!rawText) return;
            // 目的地系ステップは専用の文言で予告する
            const isDestination = /目的地/.test(rawText);
            if (isDestination) {
                this.announce({
                    id:          `pre-${stepId}`,
                    text:        'もうすぐ到着です',
                    displayText: 'まもなく目的地です',
                    category:    'maneuver',
                    msgType:     'arrival',
                    priority:    'normal',
                });
                return;
            }
            const type = _stepType(rawText);
            const voiceText = _stepVoiceText(rawText);
            console.log(`[voice] text="${voiceText}" type=${type} dist=${CONFIG.approachDistanceMeters}m`);
            this.announce({
                id:          `pre-${stepId}`,
                text:        voiceText,
                displayText: `まもなく: ${rawText}`,
                category:    'maneuver',
                msgType:     type,
                priority:    'normal',
            });
        },

        announceCrossing(upcoming) {
            if (!upcoming?.crossing?.point) return;
            const point = upcoming.crossing.point;
            const id = `crossing-${point.lat?.toFixed?.(6) || point.lat},${(point.lng ?? point.lon)?.toFixed?.(6) || (point.lng ?? point.lon)}`;
            if (state.lastCrossingId === id) return;
            const message = _crossingVoiceMessage(upcoming);
            console.log(`[voice] text="${message.text}" type=crossing signalized=${message.signalized} dist=${Math.round(upcoming.distanceM)}m`);
            const announced = this.announce({
                id,
                text:        message.text,
                displayText: message.text,
                category:    'maneuver',
                msgType:     'crossing',
                priority:    'normal',
            });
            if (announced) state.lastCrossingId = id;
        },

        checkNextInstruction(position, route) {
            if (!position || !route) return;
            this.setInstructionContext(position, route);

            const crossingInstruction = _findUpcomingCrossing(position, route);
            const turnInstruction     = _getTurnInstruction(position);
            const finalDist           = _voiceConfigNumber('navigation.final_reminder_distance', CONFIG.finalReminderDistanceM);
            const stopDist            = CONFIG.stopGuardDistanceM;

            if (crossingInstruction && crossingInstruction.distanceM <= finalDist) {
                // ── 5m直前: 横断リマインド ──────────────────────────────────────
                const pt = crossingInstruction.crossing.point;
                const finalId = `final-crossing-${pt.lat?.toFixed?.(6)},${(pt.lng ?? pt.lon)?.toFixed?.(6)}`;
                if (state.lastFinalReminderId !== finalId) {
                    const text = _finalCrossingText(crossingInstruction);
                    console.log(`[voice] text="${text}" type=crossing_final dist=${crossingInstruction.distanceM.toFixed(1)}m`);
                    const ok = this.announce({ id: finalId, text, displayText: text, category: 'maneuver', msgType: 'crossing_final', priority: 'high' });
                    if (ok) state.lastFinalReminderId = finalId;
                }
            } else if (!crossingInstruction && turnInstruction && turnInstruction.distanceM <= finalDist) {
                // ── 5m直前: 曲がり角リマインド ──────────────────────────────────
                const finalId = `final-turn-${turnInstruction.stepId}`;
                if (state.lastFinalReminderId !== finalId) {
                    const text = _finalTurnText(turnInstruction.rawText);
                    if (text) {
                        console.log(`[voice] text="${text}" type=turn_final dist=${turnInstruction.distanceM.toFixed(1)}m`);
                        const ok = this.announce({ id: finalId, text, displayText: text, category: 'maneuver', msgType: 'turn_final', priority: 'high' });
                        if (ok) state.lastFinalReminderId = finalId;
                    }
                }
            } else if (crossingInstruction && crossingInstruction.distanceM >= stopDist) {
                // ── 通常接近: 横断予告（3m以上のみ）────────────────────────────
                this.announceCrossing(crossingInstruction);
            } else if (turnInstruction && turnInstruction.distanceM >= stopDist) {
                // ── 通常接近: 曲がり角予告（3m以上のみ）────────────────────────
                this.announceStep(turnInstruction.rawText, turnInstruction.stepId, turnInstruction.distanceM);
            }
        },

        // 音声ON/OFFトグル（文字案内は常に動作）
        setEnabled(val) {
            state.enabled = !!val;
            const btn = document.getElementById('voice-nav-toggle-btn');
            if (btn) btn.classList.toggle('map-overlay-btn--active', state.enabled);
            if (!val && window.speechSynthesis) window.speechSynthesis.cancel();
        },

        // 振動ON/OFFトグル（音声・文字とは独立）
        haptics: {
            get enabled() { return hapticsState.enabled; },
            setEnabled(val) {
                hapticsState.enabled = !!val;
                if (!val && _canVibrate()) navigator.vibrate(0); // 振動を即停止
            },
        },

        // ナビ停止・再ルート時にリセット
        clear() {
            const bar = document.getElementById('nav-announcement-bar');
            if (bar) bar.style.display = 'none';
            if (state.hideTimer) { clearTimeout(state.hideTimer); state.hideTimer = null; }
            if (window.speechSynthesis) window.speechSynthesis.cancel();
            if (_canVibrate()) navigator.vibrate(0);
            state.lastMessageId       = null;
            state.lastMessageText     = null;
            state.lastSpokenAt        = 0;
            state.lastCategory        = null;
            state.lastAnnouncedType   = null;
            state.lastCrossingId      = null;
            state.lastFinalReminderId = null;
            state.instructionContext  = null;
        },
    };
})();
