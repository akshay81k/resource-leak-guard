import java.io.*;

public class PossibleLeakPassedToHelper {
    public void riskyMethod(String path) throws IOException {
        FileInputStream fis = new FileInputStream(path);
        processStream(fis);
    }

    private void processStream(FileInputStream stream) {
        // might or might not close the stream
    }
}
