/**
 * 会话状态管理
 */

import { create } from 'zustand';
import { Session, AgentMode } from '../types';

interface SessionState {
  currentSession: Session | null;
  sessions: Session[];
  mode: AgentMode;
  isConnected: boolean;
  availableTools: string[];

  // Actions
  setCurrentSession: (session: Session | null) => void;
  setSessions: (sessions: Session[]) => void;
  addSession: (session: Session) => void;
  updateSession: (sessionId: string, updates: Partial<Session>) => void;
  removeSession: (sessionId: string) => void;
  setMode: (mode: AgentMode) => void;
  setConnected: (connected: boolean) => void;
  setAvailableTools: (tools: string[]) => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  currentSession: null,
  sessions: [],
  mode: 'BUILD',
  isConnected: false,
  availableTools: [],

  setCurrentSession: (session) => {
    set({
      currentSession: session,
      mode: session?.mode || 'BUILD',
    });
  },

  setSessions: (sessions) => {
    set({ sessions });
  },

  addSession: (session) => {
    set((state) => ({
      sessions: [session, ...state.sessions],
    }));
  },

  updateSession: (sessionId, updates) => {
    set((state) => ({
      sessions: state.sessions.map((s) =>
        s.session_id === sessionId ? { ...s, ...updates } : s
      ),
      currentSession:
        state.currentSession?.session_id === sessionId
          ? { ...state.currentSession, ...updates }
          : state.currentSession,
    }));
  },

  removeSession: (sessionId) => {
    set((state) => ({
      sessions: state.sessions.filter((s) => s.session_id !== sessionId),
      currentSession:
        state.currentSession?.session_id === sessionId
          ? null
          : state.currentSession,
    }));
  },

  setMode: (mode) => {
    set({ mode });
  },

  setConnected: (connected) => {
    set({ isConnected: connected });
  },

  setAvailableTools: (tools) => {
    set({ availableTools: tools });
  },
}));
