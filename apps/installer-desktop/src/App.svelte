<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';

  type WizardStep = {
    id: string;
    question: string;
    choices: string[];
  };

  let step: WizardStep | null = null;
  let answer = '';
  let error: string | null = null;
  let done = false;

  async function advance(value: string) {
    error = null;
    try {
      const next = await invoke<WizardStep>('wizard_next', { answer: value });
      if (next.id === '__done__') {
        done = true;
        step = null;
      } else {
        step = next;
        answer = '';
      }
    } catch (e) {
      error = String(e);
    }
  }

  onMount(() => advance(''));
</script>

<main>
  <header>
    <h1>Maverick installer</h1>
    <p class="sub">Set up Maverick on this machine.</p>
  </header>

  {#if done}
    <section class="done">
      <h2>Setup complete.</h2>
      <p>Maverick is configured. Open a terminal and run <code>maverick serve</code> to start.</p>
    </section>
  {:else if step}
    <section>
      <h2>{step.question}</h2>
      {#if step.choices.length > 0}
        <ul>
          {#each step.choices as choice}
            <li>
              <button on:click={() => advance(choice)}>{choice}</button>
            </li>
          {/each}
        </ul>
      {:else}
        <input bind:value={answer} on:keydown={(e) => e.key === 'Enter' && advance(answer)} />
        <button on:click={() => advance(answer)}>Next</button>
      {/if}
    </section>
  {:else}
    <p class="loading">Loading...</p>
  {/if}

  {#if error}
    <p class="error">{error}</p>
  {/if}
</main>

<style>
  :global(body) {
    margin: 0;
    font-family: -apple-system, system-ui, sans-serif;
    background: #0d1117;
    color: #f0f6fc;
  }
  main { padding: 2rem; max-width: 720px; margin: 0 auto; }
  header { margin-bottom: 2rem; }
  h1 { font-size: 2rem; margin: 0; }
  .sub { color: #8b949e; }
  section { background: #161b22; padding: 1.5rem; border-radius: 8px; }
  h2 { margin-top: 0; font-size: 1.25rem; }
  ul { list-style: none; padding: 0; }
  li { margin: 0.5rem 0; }
  button {
    background: #238636; color: #fff; border: none; padding: 0.6rem 1rem;
    border-radius: 6px; cursor: pointer; font-size: 0.95rem; width: 100%;
    text-align: left;
  }
  button:hover { background: #2ea043; }
  input {
    width: 100%; padding: 0.6rem; border-radius: 6px; border: 1px solid #30363d;
    background: #0d1117; color: #f0f6fc; font-size: 0.95rem; margin-bottom: 0.5rem;
  }
  .done h2 { color: #2ea043; }
  .error { color: #f85149; margin-top: 1rem; }
  .loading { color: #8b949e; }
</style>
