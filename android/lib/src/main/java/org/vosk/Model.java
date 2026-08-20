package org.vosk;

import java.io.IOException;
import com.sun.jna.PointerType;

public class Model extends PointerType implements AutoCloseable {
    public Model() {
    }

    public Model(String path) throws IOException {
        super(LibVosk.vosk_model_new(path));

        if (getPointer() == null) {
            throw new IOException("Failed to create a model");
        }
    }

    /**
     * Checks whether a word can be recognized by the model.
     *
     * @param word the word to look up
     * @return the word symbol, or -1 if the word is not in the model vocabulary.
     *         Word symbol 0 is &lt;epsilon&gt;.
     */
    public int findWord(String word) {
        return LibVosk.vosk_model_find_word(this.getPointer(), word);
    }

    /**
     * Checks whether the model can be reconfigured with a runtime grammar.
     *
     * Models that ship a precompiled HCLG.fst cannot be constrained at runtime,
     * and passing a grammar to them fails. Check this before relying on one.
     *
     * @return true if runtime grammars are supported
     */
    public boolean supportsRuntimeGrammar() {
        return LibVosk.vosk_model_supports_runtime_grammar(this.getPointer()) != 0;
    }

    @Override
    public void close() {
        LibVosk.vosk_model_free(this.getPointer());
    }
}
